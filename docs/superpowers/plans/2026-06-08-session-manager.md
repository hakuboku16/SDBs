# Session Manager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 単一アクティブセッションのライフサイクル(開始/終了/clear・重複拒否・有効期限判定)と進行(プレイ申告の適用・正解者記録)を担う Discord 非依存の `SessionManager` を作る。

**Architecture:** インメモリで単一の `GameSession` を保持する `SessionManager` クラス。時刻は各メソッドへ `now: datetime` を注入し純粋・テスト容易に保つ。申告適用は Plan 3 の `play_matcher.apply_report` を `session.topics` に適用し、新規達成お題の `panel_no` を `revealed_panels` に加える。asyncio タイマー本体・予告/自動終了の送信・盤面再合成・メッセージ参照は後続(M4/M5)へ意図的に分離する。

**Tech Stack:** Python 3.12 / 標準ライブラリ(dataclasses, datetime, math.isqrt)/ pytest。新規依存なし。`src/game/models.py` に `ImageOptions` / `GameSession` を積み増し、`src/game/session_manager.py` を新設する。

---

## このプランの位置づけ(全体ロードマップ)

設計([docs/superpowers/specs/2026-06-04-deemo-attack25-bot-design.md](docs/superpowers/specs/2026-06-04-deemo-attack25-bot-design.md))のマイルストーン **M3(セッション+照合)のうちセッション(session_manager)** に対応する。依存順:

1. 楽曲データ層(完了) — models / song_repository
2. お題エンジン(完了) — predicates / topic_catalog / topic_types / topic_generator
3. プレイ照合(完了) — play_matcher
4. **セッション管理(本プラン)** — session_manager
5. 盤面描画 / bot 基盤 / スラッシュコマンド cogs

**スコープ境界(意図的):**
- **Discord 非依存・時刻注入型。** asyncio タイマー本体、残り10分予告、自動終了の Discord 送信は M4/M5 cog で配線する。本プランは状態遷移と `is_expired` / `remaining` の判定までを提供する。
- **`SessionManager` は解決済みの値を受け取る。** 隠し曲(`Song`)・お題群(`list[Topic]`)・画像加工設定(`ImageOptions`)は呼び出し側(cog / M5)で解決して渡す。曲名の部分一致解決(/report・/answer の入力)は cog 層の責務とし、manager は Discord/`SongRepository` 非依存に保つ。
- **`duration_minutes` は `start()` へ注入する。** config への session 設定追加(`session_duration_minutes` 等)は M1/設定の関心事であり本プランでは行わない。テストと cog から明示的に渡す。
- **GameSession の Discord/asyncio 結合フィールドは延期。** `board_message_ref` / `topic_message_ref` / `timer_task` は M4/M5 で追加する。`image_options` は純データのため本プランで含める。
- **盤面再合成・アーカイブ投稿は持たない。** `end()` は最終 `GameSession` を返すのみ。アーカイブ(画像合成・Discord 投稿)は M4/M5 が返り値を消費する。

## File Structure

- Modify: `src/game/models.py` — `ImageOptions`(frozen)と `GameSession`(mutable)を追記
- Create: `src/game/session_manager.py` — `SessionManager` とドメイン例外
- Test: `tests/game/test_models.py` — `ImageOptions` / `GameSession` 構築テストを追記
- Create: `tests/game/test_session_manager.py` — ライフサイクルと進行のテスト

---

## Task 1: セッション状態モデル(ImageOptions / GameSession)

照合の上位に位置するセッション状態を `models.py` に追加する。`ImageOptions` は開始時に解決済みの加工設定で不変のため frozen。`GameSession` は進行中に `revealed_panels` / `correct_answerers` を更新するため frozen にしない。`grid_size` は `panel_count` から導出し単一情報源に保つ。

**Files:**
- Modify: `src/game/models.py`
- Test: `tests/game/test_models.py`(追記)

- [ ] **Step 1: 失敗するテストを追記**

`tests/game/test_models.py` の先頭インポートを次へ置き換える(`GameSession` / `ImageOptions` を追加、`datetime` を導入):

```python
from datetime import datetime

from src.game.models import (
    Chart,
    Difficulty,
    GameSession,
    ImageOptions,
    PlayCondition,
    PlayReport,
    ProgressKind,
    Song,
    Topic,
    TopicType,
)
```

末尾に次のテストを追記:

```python
def test_image_options_construction() -> None:
    opts = ImageOptions(rotate=90, grayscale=True, mosaic_px=150)
    assert opts.rotate == 90
    assert opts.grayscale is True
    assert opts.mosaic_px == 150


def test_game_session_defaults_and_grid_size() -> None:
    song = Song(
        title="Dream",
        shelf="Story",
        book="Vol.1A",
        version="1.0",
        charts={Difficulty.HARD: Chart(level=8, notes=485)},
        time=133,
        composers=("Rabpit",),
        featuring=(),
        image_path=None,
    )
    session = GameSession(
        panel_count=9,
        hidden_song=song,
        image_options=ImageOptions(rotate=None, grayscale=False, mosaic_px=None),
        topics=[],
        started_at=datetime(2026, 6, 8, 12, 0, 0),
        ends_at=datetime(2026, 6, 8, 12, 30, 0),
    )
    assert session.grid_size == 3
    assert session.revealed_panels == set()
    assert session.correct_answerers == set()


def test_game_session_grid_size_for_each_panel_count() -> None:
    song = Song(
        title="Dream",
        shelf="Story",
        book="Vol.1A",
        version="1.0",
        charts={Difficulty.HARD: Chart(level=8, notes=485)},
        time=133,
        composers=("Rabpit",),
        featuring=(),
        image_path=None,
    )
    options = ImageOptions(rotate=None, grayscale=False, mosaic_px=None)
    start = datetime(2026, 6, 8, 12, 0, 0)
    end = datetime(2026, 6, 8, 12, 30, 0)
    expected = {4: 2, 9: 3, 16: 4, 25: 5}
    for panel_count, grid in expected.items():
        session = GameSession(
            panel_count=panel_count,
            hidden_song=song,
            image_options=options,
            topics=[],
            started_at=start,
            ends_at=end,
        )
        assert session.grid_size == grid
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `uv run pytest tests/game/test_models.py -k "image_options or game_session" -v`
Expected: FAIL(`ImportError: cannot import name 'ImageOptions'`)

- [ ] **Step 3: モデルを追記**

`src/game/models.py` の先頭インポートを次へ置き換える(`field` / `datetime` / `isqrt` を追加):

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from math import isqrt
from pathlib import Path
```

`src/game/models.py` の末尾(`PlayReport` dataclass の後)に追記:

```python
@dataclass(frozen=True)
class ImageOptions:
    """盤面画像への加工設定。開始時に解決済みの値を保持し以後固定。"""

    rotate: int | None
    grayscale: bool
    mosaic_px: int | None


@dataclass
class GameSession:
    """単一アクティブセッションの状態。進行で更新するため frozen にしない。"""

    panel_count: int
    hidden_song: Song
    image_options: ImageOptions
    topics: list[Topic]
    started_at: datetime
    ends_at: datetime
    revealed_panels: set[int] = field(default_factory=set)
    correct_answerers: set[int] = field(default_factory=set)

    @property
    def grid_size(self) -> int:
        # panel_count(4/9/16/25)の平方根が盤面の一辺(2/3/4/5)。
        return isqrt(self.panel_count)
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `uv run pytest tests/game/test_models.py -v`
Expected: PASS(既存 + 追加分すべて)

- [ ] **Step 5: コミット**

```bash
git add src/game/models.py tests/game/test_models.py
git commit -m "feat: セッション状態モデル(ImageOptions / GameSession)を追加" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: セッション管理(session_manager.py)

`SessionManager` でインメモリの単一アクティブセッションを管理する。`start` は重複時に `SessionAlreadyActiveError`、不正な `panel_count` で `ValueError` を送出し `ends_at = now + duration` で生成する。`apply_report` は Plan 3 の `play_matcher.apply_report` を `session.topics` に適用し新規達成の `panel_no` を `revealed_panels` に追加して新規達成リストを返す。`record_answer` は解決済み `Song` と隠し曲を照合し正解者を記録する。`is_expired` / `remaining` は注入された `now` で判定する。`end` は最終 `GameSession` を返し破棄、`clear` はアーカイブ無しで破棄する。非アクティブ時の操作は `NoActiveSessionError`。

**Files:**
- Create: `src/game/session_manager.py`
- Test: `tests/game/test_session_manager.py`

- [ ] **Step 1: 失敗するテストを書く**

Create `tests/game/test_session_manager.py`:

```python
from datetime import datetime, timedelta

import pytest

from src.game.models import (
    Chart,
    Difficulty,
    GameSession,
    ImageOptions,
    PlayCondition,
    PlayReport,
    ProgressKind,
    Song,
    Topic,
    TopicType,
)
from src.game.session_manager import (
    NoActiveSessionError,
    SessionAlreadyActiveError,
    SessionManager,
)

_NOW = datetime(2026, 6, 8, 12, 0, 0)


def _song(title: str = "Dream") -> Song:
    return Song(
        title=title,
        shelf="Story",
        book="Vol.1A",
        version="1.0",
        charts={Difficulty.HARD: Chart(level=8, notes=485)},
        time=133,
        composers=("Rabpit",),
        featuring=(),
        image_path=None,
    )


def _options() -> ImageOptions:
    return ImageOptions(rotate=None, grayscale=False, mosaic_px=None)


def _topic(
    *,
    topic_type: TopicType = TopicType.TITLE_INCLUDE,
    filter_value: object = ("d",),
    required: int = 1,
    panel_no: int = 1,
) -> Topic:
    return Topic(
        panel_no=panel_no,
        topic_type=topic_type,
        play_condition=PlayCondition.PLAY,
        filter_value=filter_value,
        required=required,
        progress_kind=ProgressKind.COUNT,
        description="dummy",
    )


def _report(song: Song | None = None) -> PlayReport:
    return PlayReport(
        song=song if song is not None else _song(),
        difficulty=Difficulty.HARD,
        combo=485,
        charming=485,
    )


def _started(
    manager: SessionManager,
    *,
    topics: list[Topic] | None = None,
    song: Song | None = None,
) -> GameSession:
    return manager.start(
        hidden_song=song if song is not None else _song(),
        image_options=_options(),
        topics=topics if topics is not None else [_topic()],
        panel_count=9,
        now=_NOW,
        duration_minutes=30,
    )


def _active(manager: SessionManager) -> GameSession:
    # active は None を返しうるため、None でないことを表明してから参照する。
    session = manager.active
    assert session is not None
    return session


def test_start_creates_active_session() -> None:
    manager = SessionManager()
    session = _started(manager)
    assert manager.active is session
    assert session.grid_size == 3
    assert session.ends_at == _NOW + timedelta(minutes=30)


def test_start_rejects_when_already_active() -> None:
    manager = SessionManager()
    _started(manager)
    with pytest.raises(SessionAlreadyActiveError):
        _started(manager)


def test_start_rejects_invalid_panel_count() -> None:
    manager = SessionManager()
    with pytest.raises(ValueError):
        manager.start(
            hidden_song=_song(),
            image_options=_options(),
            topics=[_topic()],
            panel_count=10,
            now=_NOW,
            duration_minutes=30,
        )


def test_apply_report_progresses_and_reveals_panel() -> None:
    manager = SessionManager()
    topic = _topic(required=1, panel_no=5)
    _started(manager, topics=[topic])
    newly = manager.apply_report(_report())
    assert newly == [topic]
    assert _active(manager).revealed_panels == {5}


def test_apply_report_without_session_raises() -> None:
    manager = SessionManager()
    with pytest.raises(NoActiveSessionError):
        manager.apply_report(_report())


def test_record_answer_correct_records_user() -> None:
    manager = SessionManager()
    _started(manager, song=_song("Dream"))
    assert manager.record_answer(42, _song("Dream")) is True
    assert _active(manager).correct_answerers == {42}


def test_record_answer_wrong_does_not_record() -> None:
    manager = SessionManager()
    _started(manager, song=_song("Dream"))
    assert manager.record_answer(42, _song("Nine")) is False
    assert _active(manager).correct_answerers == set()


def test_is_expired_and_remaining() -> None:
    manager = SessionManager()
    _started(manager)
    assert manager.is_expired(_NOW + timedelta(minutes=29)) is False
    assert manager.is_expired(_NOW + timedelta(minutes=30)) is True
    assert manager.remaining(_NOW + timedelta(minutes=10)) == timedelta(minutes=20)


def test_end_returns_session_and_allows_restart() -> None:
    manager = SessionManager()
    started = _started(manager)
    ended = manager.end()
    assert ended is started
    assert manager.active is None
    _started(manager)  # 終了後は再開できる
    assert manager.active is not None


def test_clear_discards_and_allows_restart() -> None:
    manager = SessionManager()
    _started(manager)
    manager.clear()
    assert manager.active is None
    _started(manager)
    assert manager.active is not None


def test_end_without_session_raises() -> None:
    manager = SessionManager()
    with pytest.raises(NoActiveSessionError):
        manager.end()


def test_clear_without_session_raises() -> None:
    manager = SessionManager()
    with pytest.raises(NoActiveSessionError):
        manager.clear()
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `uv run pytest tests/game/test_session_manager.py -v`
Expected: FAIL(`ModuleNotFoundError: No module named 'src.game.session_manager'`)

- [ ] **Step 3: session_manager.py を実装**

Create `src/game/session_manager.py`:

```python
from __future__ import annotations

from datetime import datetime, timedelta

from src.game.models import GameSession, ImageOptions, PlayReport, Song, Topic
from src.game.play_matcher import apply_report as match_play_report

_VALID_PANEL_COUNTS = frozenset({4, 9, 16, 25})


class SessionError(Exception):
    """セッション操作の基底例外。"""


class SessionAlreadyActiveError(SessionError):
    """アクティブなセッションが既に存在する。"""


class NoActiveSessionError(SessionError):
    """アクティブなセッションが存在しない。"""


class SessionManager:
    """単一プロセス内の単一アクティブセッションを管理する(再起動で揮発)。"""

    def __init__(self) -> None:
        self._session: GameSession | None = None

    @property
    def active(self) -> GameSession | None:
        return self._session

    def start(
        self,
        *,
        hidden_song: Song,
        image_options: ImageOptions,
        topics: list[Topic],
        panel_count: int,
        now: datetime,
        duration_minutes: int,
    ) -> GameSession:
        if self._session is not None:
            raise SessionAlreadyActiveError
        if panel_count not in _VALID_PANEL_COUNTS:
            raise ValueError(f"panel_count must be one of {sorted(_VALID_PANEL_COUNTS)}")
        session = GameSession(
            panel_count=panel_count,
            hidden_song=hidden_song,
            image_options=image_options,
            topics=topics,
            started_at=now,
            ends_at=now + timedelta(minutes=duration_minutes),
        )
        self._session = session
        return session

    def apply_report(self, report: PlayReport) -> list[Topic]:
        session = self._require_active()
        newly_completed = match_play_report(report, session.topics)
        for topic in newly_completed:
            session.revealed_panels.add(topic.panel_no)
        return newly_completed

    def record_answer(self, user_id: int, song: Song) -> bool:
        session = self._require_active()
        # 隠し曲との一致は解決済み Song の title で判定する。部分一致解決は cog の責務。
        correct = song.title == session.hidden_song.title
        if correct:
            session.correct_answerers.add(user_id)
        return correct

    def is_expired(self, now: datetime) -> bool:
        session = self._require_active()
        return now >= session.ends_at

    def remaining(self, now: datetime) -> timedelta:
        session = self._require_active()
        return session.ends_at - now

    def end(self) -> GameSession:
        session = self._require_active()
        self._session = None
        return session

    def clear(self) -> None:
        self._require_active()
        self._session = None

    def _require_active(self) -> GameSession:
        if self._session is None:
            raise NoActiveSessionError
        return self._session
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `uv run pytest tests/game/test_session_manager.py -v`
Expected: PASS(13 件)

- [ ] **Step 5: 全テストを実行**

Run: `uv run pytest -v`
Expected: 既存の全テストと本プランの追加分が PASS

- [ ] **Step 6: コミット**

```bash
git add src/game/session_manager.py tests/game/test_session_manager.py
git commit -m "feat: セッション管理(ライフサイクル・進行・有効期限判定)を追加" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage(M3 セッション範囲):**
- 「GameSession(panel_count/grid_size/hidden_song/image_options/topics/revealed_panels/correct_answerers/started_at/ends_at)」→ Task 1 `GameSession` ✓(`board_message_ref` / `topic_message_ref` / `timer_task` は M4/M5 へ意図的に延期)
- 「単一アクティブセッション・重複開始拒否」→ Task 2 `start` の `SessionAlreadyActiveError` ✓
- 「panels 4/9/16/25」→ Task 2 `_VALID_PANEL_COUNTS` 検証 + Task 1 `grid_size` 導出 ✓
- 「30 分タイマー」→ Task 2 `ends_at = now + duration_minutes` / `is_expired` / `remaining`(asyncio 本体・予告/自動終了送信は M4/M5)✓
- 「申告→全お題照合→新規達成パネル開示(revealed に追加)」→ Task 2 `apply_report` が `play_matcher.apply_report` を適用し `revealed_panels` 更新 ✓
- 「/answer 正解で user_id 記録」→ Task 2 `record_answer` ✓
- 「/session_end でその時点の状態をアーカイブ」→ Task 2 `end()` が最終 `GameSession` を返す(画像合成・Discord 投稿は M4/M5 が消費)✓
- 「/session_clear はアーカイブ無しで強制破棄」→ Task 2 `clear()` ✓
- 「時刻は注入可能に(テスト戦略)」→ 全時刻メソッドが `now` 引数 ✓
- **session_manager は重複開始拒否・終了アーカイブ・clear 復帰をテスト(テスト戦略)** → Task 2 の該当テスト ✓

**2. Placeholder scan:** プレースホルダなし。全ステップに実コード/実コマンドあり。

**3. Type consistency:**
- `ImageOptions(rotate: int | None, grayscale: bool, mosaic_px: int | None)` を Task 1 で定義し Task 2 のテストで同名参照。
- `GameSession`(panel_count / hidden_song / image_options / topics / started_at / ends_at / revealed_panels / correct_answerers / grid_size プロパティ)を Task 1 で定義し Task 2 で参照。
- `SessionManager.start(*, hidden_song, image_options, topics, panel_count, now, duration_minutes) -> GameSession` の引数名・キーワード専用・戻り値がテストと実装で一致。
- `apply_report(report: PlayReport) -> list[Topic]` / `record_answer(user_id: int, song: Song) -> bool` / `is_expired(now) -> bool` / `remaining(now) -> timedelta` / `end() -> GameSession` / `clear() -> None` の各シグネチャがテストと実装で一致。
- `play_matcher.apply_report(report, topics) -> list[Topic]`(Plan 3)を `match_play_report` 別名で取り込み、メソッド名 `apply_report` との衝突を回避。
- 例外 `SessionAlreadyActiveError` / `NoActiveSessionError`(基底 `SessionError`)をテストと実装で一致。

**4. 規約:** 型ヒント必須・`Any`/`unknown` 不使用・コメントは WHY のみ・docstring はテンプレート様式踏襲・関数は単一責務・manager は Discord/`SongRepository` 非依存でテスト可能。

**5. 既知の割り切り(WHY):**
- Discord/asyncio 結合(タイマー本体・予告/自動終了送信・盤面再合成・メッセージ参照)は M4/M5 へ分離し、M3 は純粋な状態遷移と判定に保つ。
- `duration_minutes` は `start()` 注入。config の session 設定追加は M1/設定の関心事のため本プランでは触れない。
- `record_answer` は解決済み `Song` を受け取り title で照合。部分一致解決は Discord の関心事のため cog 層へ分離(Plan 3 と一貫)。
- `image_options` は解決済み値オブジェクト。回転角の抽選は M5 cog、消費は M4 board。
```
