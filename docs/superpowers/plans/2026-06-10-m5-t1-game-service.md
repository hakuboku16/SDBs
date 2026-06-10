# M5-T1 GameService 足場 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** cog から呼ぶための共有サービス `GameService` を新設し、ゲーム層(`SongRepository`/`TopicGenerator`/`board`/`SessionManager`)と Discord 側のセッション文脈(盤面・お題リストメッセージ参照、タイマータスク)を集約する。あわせて `GameBot` へ結線し、アプリコマンド共通エラーハンドラを用意する。

**Architecture:** `src/bot/game_service.py` に `GameService` を置く。`game/` は Discord 非依存のまま維持し、Discord 型(`discord.Message` 等)は GameService の属性スロットとしてのみ保持する(設計書のデータモデル実装注記に対応)。本タスク(M5-T1)は Discord 非依存に切り出せるロジック(曲解決・お題リスト整形・セッション開始オーケストレーション・盤面再描画・タイマー時刻計算・エラー文整形)を TDD で実装し、メッセージ投稿・ピン留め・タイマータスクの実走行・cog 本体は後続タスク(T2/T3)へ委譲する。

**Tech Stack:** Python 3.12 / uv / pytest / discord.py / Pillow(いずれも導入済み)

---

## 現状(着手前の事実)

- ゲーム層は完成・テスト済み:
  - [src/game/song_repository.py](src/game/song_repository.py) … `SongRepository(songs)` / `from_files(songs_path, images_dir)` / `search(query)->list[Song]` / `songs_with_image()->list[Song]` / `versions()`/`books()`/`shelves()`。
  - [src/game/topic_catalog.py](src/game/topic_catalog.py) … `load_topics(topics_path)->list[TopicTemplate]`。
  - [src/game/topic_generator.py](src/game/topic_generator.py) … `generate_topics(templates, count, repo, rng)->list[Topic]`。
  - [src/game/image_options.py](src/game/image_options.py) … `resolve_image_options(*, rotate, grayscale, mosaic_px, rng)->ImageOptions`。
  - [src/game/board.py](src/game/board.py) … `render_board(image_path, *, grid_size, revealed_panels, options)->bytes`。
  - [src/game/session_manager.py](src/game/session_manager.py) … `SessionManager` (`start`/`apply_report`/`record_answer`/`is_expired`/`remaining`/`end`/`clear`、`active` プロパティ、例外 `NoActiveSessionError`/`SessionAlreadyActiveError`)。
  - [src/game/models.py](src/game/models.py) … `Song`/`Topic`/`GameSession`/`ImageOptions` 等。`GameSession` は Discord 型を持たない。
- bot 層は M1 完成:[src/bot/client.py](src/bot/client.py) の `GameBot(commands.Bot)`。`src/cogs/` は空(`__init__.py` のみ)。
- [src/core/config.py](src/core/config.py) … `BaseAppSettings` に `songs_data_path`/`topics_data_path`/`images_dir`/`session_duration_minutes`/`session_warning_minutes` を保持。`get_settings()` で環境別設定を取得。

## ファイル構成

- 作成: `src/bot/game_service.py`(`GameService` 本体・曲解決例外・整形/時刻計算のモジュール関数)
- 作成: `tests/bot/__init__.py`(空。テストパッケージ)
- 作成: `tests/bot/test_game_service.py`(Discord 非依存・実アセット非依存の単体テスト)
- 作成: `tests/bot/test_game_service_integration.py`(実アセットを読む統合テスト:start_session / render_current_board)
- 変更: `src/bot/client.py`(`GameBot` へ `GameService` 結線とアプリコマンド共通エラーハンドラ)

## 設計判断(本タスクの確定事項)

- **Discord 側状態のスロット**: `GameService` に `board_message` / `topic_message`(いずれも `object | None`、実体は後続で `discord.Message`)、`timer_task`(`asyncio.Task | None`)を持たせる。型注釈は discord 依存を避けるため最小限にする。
- **タイマー**: 本タスクでは時刻計算 `timer_delays(session, now, warning_minutes)` と `cancel_timer()` のみ実装する。実際に sleep してログ ch へ予告/自動終了を投稿する非同期タスクの生成は、投稿・アーカイブ処理を持つ T2(`/session_start`)で行う。
- **メッセージ投稿/ピン留め/`message.edit`** は T2/T3 で実装する。本タスクは「再描画に必要なバイト列/文字列を作る」ところまで。

---

## Task 1: GameService 骨格 + 曲解決

**Files:**
- Create: `src/bot/game_service.py`
- Create: `tests/bot/__init__.py`
- Test: `tests/bot/test_game_service.py`

- [ ] **Step 1: テストパッケージの空 __init__ を作成**

`tests/bot/__init__.py` を空ファイルとして作成する。

- [ ] **Step 2: 失敗するテストを書く**

`tests/bot/test_game_service.py` を新規作成する。

```python
from pathlib import Path

import pytest

from src.bot.game_service import AmbiguousSong, GameService, SongNotFound
from src.game.models import Chart, Difficulty, Song
from src.game.song_repository import SongRepository


def _song(title: str, *, image: bool = False) -> Song:
    """テスト用の最小 Song を組み立てる。

    Args:
        title: 曲名。
        image: 画像を持たせるか。True なら image_path にダミーパスを入れる。

    Returns:
        Song: 構築した楽曲。
    """
    return Song(
        title=title,
        shelf="Story",
        book="Vol.1A",
        version="1.0",
        charts={Difficulty.HARD: Chart(level=8, notes=485)},
        time=133,
        composers=("Rabpit",),
        featuring=(),
        image_path=Path("dummy.png") if image else None,
    )


def _service(songs: list[Song]) -> GameService:
    """指定楽曲を持つ GameService を組み立てる(テンプレートは空)。

    Args:
        songs: リポジトリへ載せる楽曲群。

    Returns:
        GameService: 構築したサービス。
    """
    from src.core.config import get_settings

    return GameService(repo=SongRepository(songs), templates=[], settings=get_settings())


def test_resolve_song_unique_match_returns_song() -> None:
    """部分一致が 1 件なら、その Song を返す。"""
    service = _service([_song("Dream"), _song("Pulses")])
    assert service.resolve_song("Pulses").title == "Pulses"


def test_resolve_song_no_match_raises_not_found() -> None:
    """部分一致が 0 件なら SongNotFound を送出し、query を保持する。"""
    service = _service([_song("Dream")])
    with pytest.raises(SongNotFound) as exc:
        service.resolve_song("zzz")
    assert exc.value.query == "zzz"


def test_resolve_song_multiple_matches_raises_ambiguous() -> None:
    """部分一致が複数なら AmbiguousSong を送出し、候補を保持する。"""
    service = _service([_song("Dream"), _song("Dreamy"), _song("Pulses")])
    with pytest.raises(AmbiguousSong) as exc:
        service.resolve_song("Dream")
    assert {s.title for s in exc.value.matches} == {"Dream", "Dreamy"}
```

- [ ] **Step 3: テストが失敗することを確認**

Run: `APP_ENV=test uv run pytest tests/bot/test_game_service.py -v`
Expected: FAIL(`ModuleNotFoundError: No module named 'src.bot.game_service'`)

- [ ] **Step 4: GameService 骨格と曲解決を実装**

`src/bot/game_service.py` を新規作成する。

```python
from __future__ import annotations

import random
from pathlib import Path

from src.core.config import BaseAppSettings
from src.game.models import Song
from src.game.session_manager import SessionManager
from src.game.song_repository import SongRepository
from src.game.topic_catalog import TopicTemplate, load_topics


class SongResolutionError(Exception):
    """曲名解決に関する基底例外。"""


class SongNotFound(SongResolutionError):
    """部分一致する曲が 1 件も無い。"""

    def __init__(self, query: str) -> None:
        """解決に失敗した検索語を保持する。

        Args:
            query: 解決に失敗した検索語。
        """
        super().__init__(query)
        self.query = query


class AmbiguousSong(SongResolutionError):
    """部分一致する曲が複数あり 1 件に絞れない。"""

    def __init__(self, matches: list[Song]) -> None:
        """候補となった曲群を保持する。

        Args:
            matches: 部分一致した複数の曲。
        """
        super().__init__(f"{len(matches)} matches")
        self.matches = matches


class GameService:
    """ゲーム層と Discord 側セッション文脈を集約する bot 層ファサード。

    cog はこのサービスへ委譲するだけの薄いアダプタに留める。game/ の純粋性を保つため、
    Discord 由来の状態(メッセージ参照・タイマータスク)はここに保持する。
    """

    def __init__(
        self,
        *,
        repo: SongRepository,
        templates: list[TopicTemplate],
        settings: BaseAppSettings,
        rng: random.Random | None = None,
    ) -> None:
        """依存と Discord 側状態スロットを初期化する。

        Args:
            repo: 楽曲リポジトリ。
            templates: お題テンプレート群。
            settings: アプリ設定(セッション時間・チャンネル ID 等)。
            rng: 抽選に使う乱数源。None なら既定の乱数源を使う。
        """
        self._repo = repo
        self._templates = templates
        self._settings = settings
        self._rng = rng or random.Random()
        self.session_manager = SessionManager()
        # Discord 側状態。実体は後続タスクで discord.Message / asyncio.Task を入れる。
        self.board_message: object | None = None
        self.topic_message: object | None = None
        self.timer_task: object | None = None

    @classmethod
    def from_settings(
        cls,
        settings: BaseAppSettings,
        *,
        rng: random.Random | None = None,
    ) -> GameService:
        """設定のパスから楽曲・お題を読み込んで生成する。

        Args:
            settings: アプリ設定。データパスを参照する。
            rng: 抽選に使う乱数源。None なら既定の乱数源を使う。

        Returns:
            GameService: 構築したサービス。
        """
        repo = SongRepository.from_files(
            Path(settings.songs_data_path), Path(settings.images_dir)
        )
        templates = load_topics(Path(settings.topics_data_path))
        return cls(repo=repo, templates=templates, settings=settings, rng=rng)

    def resolve_song(self, query: str) -> Song:
        """部分一致で曲を 1 件に解決する。

        Args:
            query: 検索語。

        Returns:
            Song: 一意に解決した曲。

        Raises:
            SongNotFound: 部分一致が 0 件の場合。
            AmbiguousSong: 部分一致が複数件の場合。
        """
        matches = self._repo.search(query)
        if not matches:
            raise SongNotFound(query)
        if len(matches) > 1:
            raise AmbiguousSong(matches)
        return matches[0]
```

- [ ] **Step 5: テストが通ることを確認**

Run: `APP_ENV=test uv run pytest tests/bot/test_game_service.py -v`
Expected: PASS(3 件通過)

- [ ] **Step 6: コミット**

```bash
git add src/bot/game_service.py tests/bot/__init__.py tests/bot/test_game_service.py
git commit -m "feat: GameService 骨格と部分一致曲解決を追加"
```

---

## Task 2: お題リスト整形

**Files:**
- Modify: `src/bot/game_service.py`
- Test: `tests/bot/test_game_service.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/bot/test_game_service.py` の末尾へ追記する。

```python
from src.bot.game_service import format_topic_list
from src.game.models import PlayCondition, ProgressKind, Topic, TopicType


def _topic(panel_no: int, *, progress: int, required: int, completed: bool) -> Topic:
    """テスト用のお題を組み立てる。

    Args:
        panel_no: パネル番号。
        progress: 現在の進捗。
        required: 達成に必要な値。
        completed: 達成済みか。

    Returns:
        Topic: 構築したお題。
    """
    return Topic(
        panel_no=panel_no,
        topic_type=TopicType.TITLE_INCLUDE,
        play_condition=PlayCondition.PLAY,
        filter_value=("a",),
        required=required,
        progress_kind=ProgressKind.COUNT,
        description=f"説明{panel_no}",
        progress=progress,
        completed=completed,
    )


def test_format_topic_list_orders_by_panel_and_shows_progress() -> None:
    """パネル番号順に「パネルN: 説明 [x/y]」を並べ、達成行には達成表示を付ける。"""
    topics = [
        _topic(2, progress=3, required=3, completed=True),
        _topic(1, progress=1, required=2, completed=False),
    ]
    assert format_topic_list(topics) == (
        "パネル1: 説明1 [1/2]\n"
        "パネル2: 説明2 [3/3] 達成"
    )
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `APP_ENV=test uv run pytest tests/bot/test_game_service.py::test_format_topic_list_orders_by_panel_and_shows_progress -v`
Expected: FAIL(`ImportError: cannot import name 'format_topic_list'`)

- [ ] **Step 3: 整形関数を実装**

`src/bot/game_service.py` の import 群へ `Topic` を追加する(既存の `from src.game.models import Song` 行を次へ置き換える)。

```python
from src.game.models import Song, Topic
```

同ファイルの `class GameService` 定義の直前へ、モジュール関数を追加する。

```python
def format_topic_list(topics: list[Topic]) -> str:
    """ピン留め用のお題リスト文字列を生成する。

    Args:
        topics: 表示するお題群。

    Returns:
        str: パネル番号昇順に「パネルN: 説明 [progress/required]」を改行連結した文字列。
            達成済みの行には末尾に「 達成」を付ける。
    """
    lines: list[str] = []
    for topic in sorted(topics, key=lambda t: t.panel_no):
        line = f"パネル{topic.panel_no}: {topic.description} [{topic.progress}/{topic.required}]"
        if topic.completed:
            line += " 達成"
        lines.append(line)
    return "\n".join(lines)
```

- [ ] **Step 4: テストが通ることを確認**

Run: `APP_ENV=test uv run pytest tests/bot/test_game_service.py -v`
Expected: PASS(本タスクのテストを含め全件通過)

- [ ] **Step 5: コミット**

```bash
git add src/bot/game_service.py tests/bot/test_game_service.py
git commit -m "feat: お題リスト整形(パネル順・進捗・達成表示)を追加"
```

---

## Task 3: セッション開始オーケストレーション

**Files:**
- Modify: `src/bot/game_service.py`
- Test: `tests/bot/test_game_service_integration.py`

`start_session` は「画像を持つ曲から隠し曲抽選 → 画像加工設定確定 → お題 N 個生成 → `SessionManager.start`」を束ねる。お題生成の達成可能性は実データに依存するため、本タスクのテストは実アセットを読む統合テストとする(既存 `tests/game/test_topic_generator_integration.py` と同方針)。

- [ ] **Step 1: 失敗するテストを書く**

`tests/bot/test_game_service_integration.py` を新規作成する。

```python
import random
from datetime import datetime

from src.bot.game_service import GameService
from src.core.config import get_settings

_NOW = datetime(2026, 6, 10, 12, 0, 0)


def _service() -> GameService:
    """実アセットを読み込んだ、乱数固定の GameService を作る。

    Returns:
        GameService: assets 配下の実データを保持するサービス。
    """
    return GameService.from_settings(get_settings(), rng=random.Random(0))


def test_start_session_generates_topics_and_picks_hidden_song() -> None:
    """開始でお題が panel_count 個生成され、画像を持つ隠し曲が選ばれ、アクティブになる。"""
    service = _service()
    session = service.start_session(
        panel_count=4,
        rotate=False,
        grayscale=False,
        mosaic_px=None,
        now=_NOW,
    )
    assert session.panel_count == 4
    assert len(session.topics) == 4
    assert session.hidden_song.image_path is not None
    assert service.session is session
    assert {t.panel_no for t in session.topics} == {1, 2, 3, 4}


def test_start_session_sets_ends_at_from_settings_duration() -> None:
    """ends_at は started_at + 設定の継続時間(分)になる。"""
    service = _service()
    session = service.start_session(
        panel_count=4, rotate=False, grayscale=False, mosaic_px=None, now=_NOW
    )
    duration = get_settings().session_duration_minutes
    assert (session.ends_at - session.started_at).total_seconds() == duration * 60
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `APP_ENV=test uv run pytest tests/bot/test_game_service_integration.py -v`
Expected: FAIL(`AttributeError: 'GameService' object has no attribute 'start_session'`)

- [ ] **Step 3: start_session と session プロパティを実装**

`src/bot/game_service.py` の import 群へ、お題生成・画像設定・GameSession を追加する。

`from __future__ import annotations` 直後の import 群を、以下を含む形に整える(既存行は残し、不足分を追記する)。

```python
from datetime import datetime

from src.game.image_options import resolve_image_options
from src.game.models import GameSession, Song, Topic
from src.game.topic_generator import generate_topics
```

`GameService` クラスへ `session` プロパティと `start_session` メソッドを追加する(`resolve_song` の後ろに置く)。

```python
    @property
    def session(self) -> GameSession | None:
        """現在のアクティブセッションを返す。

        Returns:
            GameSession | None: アクティブセッション。無ければ None。
        """
        return self.session_manager.active

    def start_session(
        self,
        *,
        panel_count: int,
        rotate: bool,
        grayscale: bool,
        mosaic_px: int | None,
        now: datetime,
    ) -> GameSession:
        """隠し曲抽選・画像設定確定・お題生成を束ねてセッションを開始する。

        Args:
            panel_count: 盤面パネル数。4/9/16/25 のいずれか。
            rotate: 回転を行うか。
            grayscale: グレースケール化するか。
            mosaic_px: モザイクの縮小先 px。None ならモザイクなし。
            now: 開始時刻。ends_at の基準に使う。

        Returns:
            GameSession: 開始して保持したセッション。

        Raises:
            SessionAlreadyActiveError: 既にアクティブなセッションがある場合。
            ValueError: panel_count が 4/9/16/25 のいずれでもない場合。
        """
        hidden_song = self._rng.choice(self._repo.songs_with_image())
        image_options = resolve_image_options(
            rotate=rotate, grayscale=grayscale, mosaic_px=mosaic_px, rng=self._rng
        )
        topics = generate_topics(self._templates, panel_count, self._repo, self._rng)
        return self.session_manager.start(
            hidden_song=hidden_song,
            image_options=image_options,
            topics=topics,
            panel_count=panel_count,
            now=now,
            duration_minutes=self._settings.session_duration_minutes,
        )
```

- [ ] **Step 4: テストが通ることを確認**

Run: `APP_ENV=test uv run pytest tests/bot/test_game_service_integration.py -v`
Expected: PASS(2 件通過)

- [ ] **Step 5: コミット**

```bash
git add src/bot/game_service.py tests/bot/test_game_service_integration.py
git commit -m "feat: セッション開始オーケストレーション(隠し曲抽選・お題生成)を追加"
```

---

## Task 4: 盤面再描画 + タイマー時刻計算

**Files:**
- Modify: `src/bot/game_service.py`
- Test: `tests/bot/test_game_service.py`, `tests/bot/test_game_service_integration.py`

- [ ] **Step 1: 失敗するテスト(時刻計算・cancel)を書く**

`tests/bot/test_game_service.py` の末尾へ追記する。

```python
from datetime import datetime, timedelta

from src.bot.game_service import timer_delays
from src.game.models import GameSession, ImageOptions


def _session_for_timer(now: datetime) -> GameSession:
    """タイマー計算用に ends_at だけ意味を持つ最小セッションを作る。

    Args:
        now: started_at。ends_at は now+30 分にする。

    Returns:
        GameSession: 計算対象のセッション。
    """
    return GameSession(
        panel_count=4,
        hidden_song=_song("Dream", image=True),
        image_options=ImageOptions(rotate=None, grayscale=False, mosaic_px=None),
        topics=[],
        started_at=now,
        ends_at=now + timedelta(minutes=30),
    )


def test_timer_delays_returns_warning_and_end_seconds() -> None:
    """予告は ends_at の warning 分前、終了は ends_at までの秒数を返す。"""
    now = datetime(2026, 6, 10, 12, 0, 0)
    warn, end = timer_delays(_session_for_timer(now), now=now, warning_minutes=10)
    assert (warn, end) == (1200.0, 1800.0)


def test_cancel_timer_is_noop_without_task() -> None:
    """タイマータスク未設定でも cancel_timer は例外を出さない。"""
    service = _service([_song("Dream")])
    service.cancel_timer()  # 何も起きない
    assert service.timer_task is None
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `APP_ENV=test uv run pytest tests/bot/test_game_service.py -k "timer or cancel" -v`
Expected: FAIL(`ImportError: cannot import name 'timer_delays'`)

- [ ] **Step 3: timer_delays / cancel_timer / render_current_board を実装**

`src/bot/game_service.py` の `format_topic_list` 関数の直後(まだ `GameService` クラスの外)へ、時刻計算関数を追加する。

```python
def timer_delays(
    session: GameSession, *, now: datetime, warning_minutes: int
) -> tuple[float, float]:
    """セッションの予告までと終了までの待機秒数を計算する。

    Args:
        session: 対象セッション。ends_at を基準にする。
        now: 現在時刻。
        warning_minutes: 終了の何分前に予告するか。

    Returns:
        tuple[float, float]: (予告までの秒数, 終了までの秒数)。
    """
    end_seconds = (session.ends_at - now).total_seconds()
    warning_seconds = end_seconds - warning_minutes * 60
    return warning_seconds, end_seconds
```

`src/bot/game_service.py` の import 群へ `render_board` を追加する。

```python
from src.game.board import render_board
```

`GameService` クラスへ `render_current_board` と `cancel_timer` を追加する(`start_session` の後ろに置く)。

```python
    def render_current_board(self) -> bytes:
        """アクティブセッションの現在の盤面 PNG を生成する。

        Returns:
            bytes: PNG エンコードした盤面画像。

        Raises:
            NoActiveSessionError: アクティブなセッションが無い場合。
        """
        session = self.session_manager._require_active()
        assert session.hidden_song.image_path is not None  # 隠し曲は画像保有曲から抽選済み
        return render_board(
            session.hidden_song.image_path,
            grid_size=session.grid_size,
            revealed_panels=session.revealed_panels,
            options=session.image_options,
        )

    def cancel_timer(self) -> None:
        """進行中のタイマータスクがあれば取り消す。"""
        # 手動終了/強制クリア時に自動終了タイマーが二重発火しないよう取り消す。
        if self.timer_task is not None:
            self.timer_task.cancel()
            self.timer_task = None
```

`render_current_board` は `SessionManager._require_active()` を使う。`game_service.py` の import 群へ次を追加する。

```python
from src.game.session_manager import NoActiveSessionError, SessionManager
```

(既存の `from src.game.session_manager import SessionManager` 行を上記へ置き換える。`NoActiveSessionError` は docstring の Raises と整合させるために import する。)

- [ ] **Step 4: 失敗する統合テスト(描画)を書く**

`tests/bot/test_game_service_integration.py` の末尾へ追記する。

```python
from io import BytesIO

from PIL import Image


def test_render_current_board_returns_300px_png() -> None:
    """開始後の盤面描画は 300px 正方の PNG を返す。"""
    service = _service()
    service.start_session(
        panel_count=4, rotate=False, grayscale=False, mosaic_px=None, now=_NOW
    )
    out = Image.open(BytesIO(service.render_current_board()))
    assert out.format == "PNG"
    assert out.size == (300, 300)
```

- [ ] **Step 5: テストが通ることを確認**

Run: `APP_ENV=test uv run pytest tests/bot/ -v`
Expected: PASS(`tests/bot/` 配下が全件通過)

- [ ] **Step 6: コミット**

```bash
git add src/bot/game_service.py tests/bot/test_game_service.py tests/bot/test_game_service_integration.py
git commit -m "feat: 盤面再描画とタイマー時刻計算・タイマー取消を追加"
```

---

## Task 5: アプリコマンド共通エラーハンドラ

**Files:**
- Modify: `src/bot/game_service.py`
- Modify: `src/bot/client.py`
- Test: `tests/bot/test_game_service.py`

利用者へ返す汎用文言は純粋関数として TDD し、`tree.on_error` への結線は `GameBot` 側で行う(実発火は手動結合テスト)。

- [ ] **Step 1: 失敗するテストを書く**

`tests/bot/test_game_service.py` の末尾へ追記する。

```python
from src.bot.game_service import GENERIC_ERROR_MESSAGE


def test_generic_error_message_is_user_facing_japanese() -> None:
    """汎用エラー文言は内部情報を含まない利用者向けの定型文である。"""
    assert "エラー" in GENERIC_ERROR_MESSAGE
    assert "Traceback" not in GENERIC_ERROR_MESSAGE
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `APP_ENV=test uv run pytest tests/bot/test_game_service.py::test_generic_error_message_is_user_facing_japanese -v`
Expected: FAIL(`ImportError: cannot import name 'GENERIC_ERROR_MESSAGE'`)

- [ ] **Step 3: 定型文言を定義**

`src/bot/game_service.py` の import 群の直後(モジュール先頭付近)へ定数を追加する。

```python
GENERIC_ERROR_MESSAGE = "コマンドの実行中にエラーが発生しました。しばらくして再度お試しください。"
```

- [ ] **Step 4: テストが通ることを確認**

Run: `APP_ENV=test uv run pytest tests/bot/test_game_service.py -v`
Expected: PASS(全件通過)

- [ ] **Step 5: GameBot へ共通エラーハンドラを結線**

[src/bot/client.py](src/bot/client.py) の import 群へ次を追加する(`from discord.ext import commands` の直後)。

```python
from discord import app_commands

from src.bot.game_service import GENERIC_ERROR_MESSAGE
```

`GameBot.setup_hook` を、cog ロード後にエラーハンドラを結線する形へ置き換える。

```python
    async def setup_hook(self) -> None:
        """接続前に cog をロードし、アプリコマンド共通エラーハンドラを結線する。"""
        await self._load_cogs()
        self.tree.on_error = self._on_app_command_error
```

`GameBot` クラスへハンドラメソッドを追加する(`_consume_log_queue` の後ろに置く)。

```python
    async def _on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        """アプリコマンドの未捕捉例外を ERROR ログへ記録し、利用者へ汎用応答する。

        Args:
            interaction: 例外が発生したコマンドのインタラクション。
            error: 捕捉したアプリコマンド例外。
        """
        logger.error("app command error: %s", error, exc_info=error)
        # 応答済みか未応答かで送出口が異なるため分岐する(二重応答を避ける)。
        if interaction.response.is_done():
            await interaction.followup.send(GENERIC_ERROR_MESSAGE, ephemeral=True)
        else:
            await interaction.response.send_message(GENERIC_ERROR_MESSAGE, ephemeral=True)
```

- [ ] **Step 6: インポート・スモークで検証**

Run: `uv run python -c "import src.bot.client; print('ok')"`
Expected: `ok`

- [ ] **Step 7: コミット**

```bash
git add src/bot/game_service.py src/bot/client.py tests/bot/test_game_service.py
git commit -m "feat: アプリコマンド共通エラーハンドラと汎用エラー文言を追加"
```

---

## Task 6: GameBot へ GameService を結線

**Files:**
- Modify: `src/bot/client.py`
- Test: `tests/bot/test_client.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/bot/test_client.py` を新規作成する。

```python
from src.bot.client import GameBot
from src.bot.game_service import GameService
from src.core.config import get_settings


def test_gamebot_exposes_game_service() -> None:
    """GameBot は GameService を game 属性として保持する。"""
    bot = GameBot(get_settings())
    assert isinstance(bot.game, GameService)
    assert bot.game.session is None
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `APP_ENV=test uv run pytest tests/bot/test_client.py -v`
Expected: FAIL(`AttributeError: 'GameBot' object has no attribute 'game'`)

- [ ] **Step 3: GameBot.__init__ で GameService を構築**

[src/bot/client.py](src/bot/client.py) の import 群へ次を追加する。

```python
from src.bot.game_service import GameService
```

(Task 5 で `from src.bot.game_service import GENERIC_ERROR_MESSAGE` を追加済みのため、1 行へまとめる:`from src.bot.game_service import GENERIC_ERROR_MESSAGE, GameService`)

`GameBot.__init__` の末尾(`self._log_started = False` の直後)へ次を追加する。

```python
        self.game = GameService.from_settings(settings)
```

- [ ] **Step 4: テストが通ることを確認**

Run: `APP_ENV=test uv run pytest tests/bot/test_client.py -v`
Expected: PASS(1 件通過)

- [ ] **Step 5: 全自動テストの回帰確認**

Run: `APP_ENV=test uv run pytest -q`
Expected: PASS(既存 + 本計画で追加したテストが全件通過)

- [ ] **Step 6: インポート・スモークで検証**

Run: `uv run python -c "import src.main; print('ok')"`
Expected: `ok`

- [ ] **Step 7: コミット**

```bash
git add src/bot/client.py tests/bot/test_client.py
git commit -m "feat: GameBot へ GameService を結線し game 属性で公開"
```

---

## 手動結合テスト(実機・自動化対象外)

本タスクは cog 本体を追加しないため、実機での新規挙動は無い。Task 6 までで `uv run python -m src.main` が起動し、`bot ready` が出ること(M1 と同等)のみ確認すれば足りる。コマンドの実発火・エラーハンドラ発火・盤面投稿は T2/T3 で検証する。

---

## このタスクで実装しないこと(T2/T3 へ委譲)

- 6 cog 本体(`session_start`/`session_end`/`session_progress`/`session_clear`/`song_report`/`answer`)。
- 盤面・お題リストメッセージの投稿/ピン留め/`message.edit` による差し替え(本タスクは描画バイト列・整形文字列の生成まで)。
- タイマーの非同期タスク生成と予告/自動終了の投稿(本タスクは `timer_delays`/`cancel_timer` まで。タスク生成は T2 の `/session_start`)。
- アーカイブ投稿・正解者発表・`/report` の該当お題 embed。
- `AmbiguousSong`/`SongNotFound` を捕捉した ephemeral 案内(捕捉する cog は T2/T3)。

---

## Self-Review(立案者チェック結果)

- **スペック対応**: 設計書の「共有サービス集約・game/ 非依存維持(GameSession 実装注記)」→ `GameService`(Task 1)。曲の部分一致解決(0/複数件)→ `resolve_song`+例外(Task 1)。ピン留めお題リスト整形「パネルN: 説明 [x/y]」→ `format_topic_list`(Task 2)。/session_start の隠し曲抽選・画像加工確定・お題 N 個生成 → `start_session`(Task 3)。盤面再合成・30 分/予告タイマー → `render_current_board`/`timer_delays`/`cancel_timer`(Task 4)。アプリコマンド共通エラーハンドラ → Task 5。bot への DI 結線 → Task 6。
- **プレースホルダ無し**: 各ステップに実コード・実コマンド・期待結果を記載。
- **型整合**: `GameService(repo, templates, settings, rng=None)` / `from_settings(settings, *, rng=None)` / `resolve_song(query)->Song` / `start_session(*, panel_count, rotate, grayscale, mosaic_px, now)->GameSession` / `render_current_board()->bytes` / `timer_delays(session, *, now, warning_minutes)->tuple[float,float]` / `cancel_timer()` / モジュール関数 `format_topic_list(topics)->str` をタスク間で一貫使用。`SongRepository`/`generate_topics`/`resolve_image_options`/`render_board`/`SessionManager.start` の各シグネチャは現行実装(本計画「現状」節)と一致。
- **実データ依存の切り分け**: お題生成の達成可能性は実データに依存するため、`start_session`/`render_current_board` のテストは実アセットを読む統合テスト(`get_settings()` 経由)とし、`resolve_song`/`format_topic_list`/`timer_delays`/エラー文言は実データ非依存の単体テストにした。
- **import 整合の注意**: `game_service.py` の `from src.game.models import ...` と `from src.game.session_manager import ...` は Task をまたいで対象を追加する。各 Task の指示どおり「既存行を置き換え」る形で重複 import を避けること。
```
