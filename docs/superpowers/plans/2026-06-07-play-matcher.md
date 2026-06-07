# Play Matcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** プレイ申告(`PlayReport`)1 件を全お題に照合し、進捗を加算して新規達成お題を返す Discord 非依存の照合エンジンを作る。

**Architecture:** Plan 2 の述語レジストリ(`PREDICATE_BUILDERS`)で楽曲フィルタを判定し、`PlayCondition`(play/FC/AC)をプレイ申告の combo/charming と譜面の notes で評価する。COUNT 型は条件成立で +1、SUM 型(level_total / result_combo_total / result_charming_total)は型ごとの抽出値を累積する。Plan 2 で意図的に後回しにした「SUM 型の累積値抽出」をここで実装する。

**Tech Stack:** Python 3.12 / 標準ライブラリ(dataclasses, enum, typing)/ pytest。新規依存なし。`src/game/models.py` に `PlayReport` を積み増し、`src/game/play_matcher.py` を新設する。

---

## このプランの位置づけ(全体ロードマップ)

設計([docs/superpowers/specs/2026-06-04-deemo-attack25-bot-design.md](docs/superpowers/specs/2026-06-04-deemo-attack25-bot-design.md))のマイルストーン **M3(セッション+照合)のうち照合(play_matcher)** に対応する。依存順:

1. 楽曲データ層(完了) — models / song_repository
2. お題エンジン(完了) — predicates / topic_catalog / topic_types / topic_generator
3. **プレイ照合(本プラン)** — play_matcher
4. セッション管理(後続プラン) — session_manager(ライフサイクル・タイマー・盤面状態)
5. 盤面描画 / bot 基盤 / スラッシュコマンド cogs

**スコープ境界(意図的):**
- **本プランは play_matcher のみ。** session_manager(単一アクティブセッション・30 分タイマー・revealed_panels)は後続プランに分離する。M3 を照合とセッションに二分する。
- **`PlayReport.song` は解決済みの `Song`。** 曲名の部分一致解決(`/report` の入力)は cog 層(M5)の責務であり、matcher は Discord/`SongRepository` 非依存に保つ。
- **不正難易度(申告難易度の譜面が曲に存在しない)はスキップ。** matcher は例外を出さず空リストを返す。利用者への「申告難易度の譜面がこの曲に存在しません」という ephemeral embed 通知は cog 層(後続プラン)の責務とし、cog が `report.difficulty not in report.song.charts` を判定して通知する。本プランでは matcher のスキップ挙動とそのテストまで。

## File Structure

- Modify: `src/game/models.py` — `PlayReport`(解決済み `Song` + 申告値)を追記
- Create: `src/game/play_matcher.py` — `apply_report` とプレイ種別判定・SUM 値抽出レジストリ
- Test: `tests/game/test_models.py` — `PlayReport` 構築テストを追記
- Create: `tests/game/test_play_matcher.py` — 照合のテーブル駆動テスト

---

## Task 1: プレイ申告モデル(PlayReport)

照合の入力となる申告 1 件を `models.py` に追加する。申告は照合中に変更しないため frozen にする。`song` は cog 層で部分一致解決済みの `Song` を受け取る。

**Files:**
- Modify: `src/game/models.py`
- Test: `tests/game/test_models.py`(追記)

- [ ] **Step 1: 失敗するテストを追記**

`tests/game/test_models.py` の先頭インポートに `PlayReport` を追加する。現状のインポートは次の通り:

```python
from src.game.models import (
    Chart,
    Difficulty,
    PlayCondition,
    ProgressKind,
    Song,
    Topic,
    TopicType,
)
```

これを次へ置き換える:

```python
from src.game.models import (
    Chart,
    Difficulty,
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
def test_play_report_construction() -> None:
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
    report = PlayReport(
        song=song,
        difficulty=Difficulty.HARD,
        combo=485,
        charming=400,
    )
    assert report.song.title == "Dream"
    assert report.difficulty is Difficulty.HARD
    assert report.combo == 485
    assert report.charming == 400
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `uv run pytest tests/game/test_models.py -k play_report -v`
Expected: FAIL(`ImportError: cannot import name 'PlayReport'`)

- [ ] **Step 3: モデルを追記**

`src/game/models.py` の末尾(`Topic` dataclass の後)に追記:

```python
@dataclass(frozen=True)
class PlayReport:
    """プレイ申告 1 件。song は cog 層で解決済みの Song。照合中は不変。"""

    song: Song
    difficulty: Difficulty
    combo: int
    charming: int
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `uv run pytest tests/game/test_models.py -v`
Expected: PASS(既存 + 追加分すべて)

- [ ] **Step 5: コミット**

```bash
git add src/game/models.py tests/game/test_models.py
git commit -m "feat: プレイ申告モデル(PlayReport)を追加" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: プレイ照合(play_matcher.py)

`apply_report(report, topics)` で全お題を走査し、楽曲フィルタ述語(Plan 2)とプレイ種別条件の両方を満たすお題の進捗を加算する。COUNT 型は +1、SUM 型は型ごとの抽出値(level/combo/charming)を累積する。閾値到達で `completed = True` にし、**この呼び出しで新規に完了したお題のリスト**を返す。不正難易度の申告はスキップして空リストを返す。

**Files:**
- Create: `src/game/play_matcher.py`
- Test: `tests/game/test_play_matcher.py`

- [ ] **Step 1: 失敗するテストを書く**

Create `tests/game/test_play_matcher.py`:

```python
from src.game.models import (
    Chart,
    Difficulty,
    PlayCondition,
    PlayReport,
    ProgressKind,
    Song,
    Topic,
    TopicType,
)
from src.game.play_matcher import apply_report


def _song(
    *,
    title: str = "Dream",
    charts: dict[Difficulty, Chart] | None = None,
    composers: tuple[str, ...] = ("Rabpit",),
) -> Song:
    if charts is None:
        charts = {Difficulty.HARD: Chart(level=8, notes=485)}
    return Song(
        title=title,
        shelf="Story",
        book="Vol.1A",
        version="1.0",
        charts=charts,
        time=133,
        composers=composers,
        featuring=(),
        image_path=None,
    )


def _report(
    *,
    song: Song | None = None,
    difficulty: Difficulty = Difficulty.HARD,
    combo: int = 485,
    charming: int = 485,
) -> PlayReport:
    return PlayReport(
        song=song if song is not None else _song(),
        difficulty=difficulty,
        combo=combo,
        charming=charming,
    )


def _topic(
    *,
    topic_type: TopicType = TopicType.TITLE_INCLUDE,
    play_condition: PlayCondition = PlayCondition.PLAY,
    filter_value: object = ("d",),
    required: int = 1,
    progress_kind: ProgressKind = ProgressKind.COUNT,
    panel_no: int = 1,
) -> Topic:
    return Topic(
        panel_no=panel_no,
        topic_type=topic_type,
        play_condition=play_condition,
        filter_value=filter_value,
        required=required,
        progress_kind=progress_kind,
        description="dummy",
    )


def test_count_increments_on_filter_match() -> None:
    topic = _topic(required=2)
    assert apply_report(_report(), [topic]) == []
    assert topic.progress == 1 and topic.completed is False
    newly = apply_report(_report(), [topic])
    assert topic.progress == 2 and topic.completed is True
    assert newly == [topic]


def test_no_progress_when_filter_unmatched() -> None:
    topic = _topic(filter_value=("z",), required=1)
    assert apply_report(_report(), [topic]) == []
    assert topic.progress == 0 and topic.completed is False


def test_full_combo_condition() -> None:
    topic = _topic(play_condition=PlayCondition.FULL_COMBO, required=1)
    # combo != notes(485) → 成立しない
    assert apply_report(_report(combo=400), [topic]) == []
    assert topic.progress == 0
    # combo == notes → 成立
    newly = apply_report(_report(combo=485), [topic])
    assert topic.completed is True and newly == [topic]


def test_all_charming_condition() -> None:
    topic = _topic(play_condition=PlayCondition.ALL_CHARMING, required=1)
    # combo == notes だが charming != notes → 成立しない
    assert apply_report(_report(combo=485, charming=400), [topic]) == []
    assert topic.progress == 0
    # combo == notes かつ charming == notes → 成立
    newly = apply_report(_report(combo=485, charming=485), [topic])
    assert topic.completed is True and newly == [topic]


def test_sum_level_total_accumulates_chart_level() -> None:
    topic = _topic(
        topic_type=TopicType.LEVEL_TOTAL,
        filter_value=None,
        required=16,
        progress_kind=ProgressKind.SUM,
    )
    apply_report(_report(), [topic])  # HARD chart level 8
    assert topic.progress == 8 and topic.completed is False
    newly = apply_report(_report(), [topic])
    assert topic.progress == 16 and topic.completed is True and newly == [topic]


def test_sum_combo_total_accumulates_combo() -> None:
    topic = _topic(
        topic_type=TopicType.RESULT_COMBO_TOTAL,
        filter_value=None,
        required=800,
        progress_kind=ProgressKind.SUM,
    )
    apply_report(_report(combo=485), [topic])
    assert topic.progress == 485
    newly = apply_report(_report(combo=485), [topic])
    assert topic.progress == 970 and topic.completed is True and newly == [topic]


def test_sum_charming_total_accumulates_charming() -> None:
    topic = _topic(
        topic_type=TopicType.RESULT_CHARMING_TOTAL,
        filter_value=None,
        required=400,
        progress_kind=ProgressKind.SUM,
    )
    apply_report(_report(charming=300), [topic])
    assert topic.progress == 300
    newly = apply_report(_report(charming=300), [topic])
    assert topic.progress == 600 and topic.completed is True and newly == [topic]


def test_sum_respects_play_condition() -> None:
    topic = _topic(
        topic_type=TopicType.LEVEL_TOTAL,
        play_condition=PlayCondition.FULL_COMBO,
        filter_value=None,
        required=8,
        progress_kind=ProgressKind.SUM,
    )
    # combo != notes → 累積しない
    assert apply_report(_report(combo=400), [topic]) == []
    assert topic.progress == 0
    # combo == notes → level を累積
    newly = apply_report(_report(combo=485), [topic])
    assert topic.progress == 8 and topic.completed is True and newly == [topic]


def test_invalid_difficulty_is_skipped() -> None:
    # 曲は HARD 譜面のみ。EASY 申告は照合せずスキップ。
    song = _song(charts={Difficulty.HARD: Chart(level=8, notes=485)})
    topic = _topic(required=1)
    newly = apply_report(_report(song=song, difficulty=Difficulty.EASY), [topic])
    assert newly == []
    assert topic.progress == 0 and topic.completed is False


def test_completed_topic_is_not_reprogressed() -> None:
    topic = _topic(required=1)
    topic.progress = 1
    topic.completed = True
    newly = apply_report(_report(), [topic])
    assert newly == []
    assert topic.progress == 1


def test_one_report_progresses_multiple_topics() -> None:
    title_topic = _topic(topic_type=TopicType.TITLE_INCLUDE, filter_value=("d",), required=1, panel_no=1)
    level_topic = _topic(topic_type=TopicType.LEVEL, filter_value=8, required=1, panel_no=2)
    newly = apply_report(_report(), [title_topic, level_topic])
    assert title_topic.completed is True and level_topic.completed is True
    assert set(newly) == {title_topic, level_topic}
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `uv run pytest tests/game/test_play_matcher.py -v`
Expected: FAIL(`ModuleNotFoundError: No module named 'src.game.play_matcher'`)

- [ ] **Step 3: play_matcher.py を実装**

Create `src/game/play_matcher.py`:

```python
from __future__ import annotations

from collections.abc import Callable

from src.game.models import (
    Chart,
    PlayCondition,
    PlayReport,
    ProgressKind,
    Topic,
    TopicType,
)
from src.game.predicates import PREDICATE_BUILDERS

# SUM 型ごとの累積値。COUNT 型は対象外(常に +1 のため登録しない)。
_SUM_VALUE_EXTRACTORS: dict[TopicType, Callable[[PlayReport, Chart], int]] = {
    TopicType.LEVEL_TOTAL: lambda report, chart: chart.level,
    TopicType.RESULT_COMBO_TOTAL: lambda report, chart: report.combo,
    TopicType.RESULT_CHARMING_TOTAL: lambda report, chart: report.charming,
}


def _play_condition_met(condition: PlayCondition, report: PlayReport, chart: Chart) -> bool:
    # FC/AC は申告 combo/charming が当該難易度の総ノーツ数に一致するかで判定する。
    if condition is PlayCondition.PLAY:
        return True
    if condition is PlayCondition.FULL_COMBO:
        return report.combo == chart.notes
    return report.combo == chart.notes and report.charming == chart.notes


def apply_report(report: PlayReport, topics: list[Topic]) -> list[Topic]:
    # 申告難易度の譜面が無い曲は FC/AC 判定も SUM 抽出もできないため照合せずスキップ。
    chart = report.song.charts.get(report.difficulty)
    if chart is None:
        return []
    newly_completed: list[Topic] = []
    for topic in topics:
        if topic.completed:
            continue
        predicate = PREDICATE_BUILDERS[topic.topic_type](topic.filter_value)
        if not predicate(report.song, report.difficulty):
            continue
        if not _play_condition_met(topic.play_condition, report, chart):
            continue
        if topic.progress_kind is ProgressKind.SUM:
            topic.progress += _SUM_VALUE_EXTRACTORS[topic.topic_type](report, chart)
        else:
            topic.progress += 1
        if topic.progress >= topic.required:
            topic.completed = True
            newly_completed.append(topic)
    return newly_completed
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `uv run pytest tests/game/test_play_matcher.py -v`
Expected: PASS(11 件)

- [ ] **Step 5: 全テストを実行**

Run: `uv run pytest -v`
Expected: 既存の全テストと本プランの追加分が PASS

- [ ] **Step 6: コミット**

```bash
git add src/game/play_matcher.py tests/game/test_play_matcher.py
git commit -m "feat: プレイ照合(進捗加算・SUM累積・達成検出)を追加" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage(M3 照合範囲):**
- 「PlayReport(song/difficulty/combo/charming)」→ Task 1 `PlayReport` ✓
- 「PlayReport 1 件を全お題に照合」→ Task 2 `apply_report` の全 topics 走査 ✓
- 「COUNT 型: 楽曲フィルタ一致 かつ プレイ種別条件で +1」→ Task 2 COUNT 分岐 + `PREDICATE_BUILDERS` + `_play_condition_met` ✓
- 「プレイ: 常時成立 / FC: combo==NOTES / AC: combo==NOTES かつ charming==NOTES」→ Task 2 `_play_condition_met` ✓
- 「SUM 型(level_total/result_combo_total/result_charming_total): フィルタ一致 かつ プレイ種別条件を満たす申告値のみ累積」→ Task 2 `_SUM_VALUE_EXTRACTORS` + SUM 分岐(プレイ種別条件を通過後に累積)✓
- 「閾値到達で達成」→ Task 2 `progress >= required` ✓
- 「新規達成お題を検出(→ panel_no を revealed に追加し再合成)」→ Task 2 が新規完了 Topic を返す。revealed 追加・再合成は session_manager / board(後続)で消費 ✓
- **不正難易度のスキップ** → Task 2 `charts.get` ガード ✓。利用者への ephemeral embed 通知は cog 層(後続)へ意図的に分離。
- **session_manager(ライフサイクル・タイマー・revealed_panels)** → 後続プランへ意図的に分離。

**2. Placeholder scan:** プレースホルダなし。全ステップに実コード/実コマンドあり。

**3. Type consistency:**
- `PlayReport(song: Song, difficulty: Difficulty, combo: int, charming: int)` を Task 1 で定義し Task 2 のテスト・実装で同名参照。
- `apply_report(report: PlayReport, topics: list[Topic]) -> list[Topic]` の引数名・順序・戻り値(新規完了 Topic 群)が実装とテストで一致。
- `Topic`(progress: int / completed: bool / progress_kind / topic_type / play_condition / filter_value / required)は Plan 2 の定義と照合箇所で一致。
- `PREDICATE_BUILDERS[topic_type](filter_value)(song, difficulty)` の呼び出し形が Plan 2 の `PredicateBuilder = Callable[[FilterValue], Predicate]` / `Predicate = Callable[[Song, Difficulty], bool]` と一致。
- `Chart.notes` / `Chart.level` を FC/AC 判定と SUM 抽出で参照(Plan 1 の `Chart` 定義に整合)。

**4. 規約:** 型ヒント必須・`Any` 不使用・コメントは WHY のみ・docstring はテンプレート様式踏襲・関数は単一責務・matcher は Discord/`SongRepository` 非依存でテスト可能。

**5. 既知の割り切り(WHY):**
- `PlayReport.song` は解決済み `Song`。部分一致解決を cog に寄せ、matcher を純粋な照合ロジックに保つ。
- 不正難易度は matcher ではスキップのみ。UI 通知(ephemeral embed)は Discord の関心事のため cog 層へ分離。
- SUM 値抽出は matcher 内のレジストリに置く。`topic_types` は生成・説明整形の関心事に保ち、照合の関心事と混ぜない。
- `progress` は int 累積(level/combo/charming はいずれも int)。
