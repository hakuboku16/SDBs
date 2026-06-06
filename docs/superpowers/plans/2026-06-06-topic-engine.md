# Topic Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `all_topics.json` のテンプレートと楽曲データから、実在曲で必ず達成可能な「お題」を N 個生成する Discord 非依存のエンジンを作る。

**Architecture:** 楽曲フィルタを `predicates.py`(型ごとの述語 `(Song, Difficulty) -> bool`)に集約し、生成(達成可能性検証)と Plan 3 の照合の両方から再利用する。`topic_catalog.py` がテンプレートを読み、`topic_types.py` が型ごとの進捗種別と value 整形をレジストリ化し、`topic_generator.py` が「テンプレ選択 → set/value/プレイ種別抽選 → 達成可能性検証 → 説明整形」で Topic を組み立てる。Topic はデータレコードに留め、述語は型 + 解決済み値から再構築する(Plan 3 でも同じ仕組みを使う)。

**Tech Stack:** Python 3.12 / 標準ライブラリ(json, random, dataclasses, enum, typing)/ pytest。新規依存なし。Plan 1 の `src/game/models.py` / `src/game/song_repository.py` に積み増す。

---

## このプランの位置づけ(全体ロードマップ)

設計([docs/superpowers/specs/2026-06-04-deemo-attack25-bot-design.md](docs/superpowers/specs/2026-06-04-deemo-attack25-bot-design.md))のマイルストーン **M2(お題生成)** に対応する。依存順:

1. 楽曲データ層(完了) — models / song_repository
2. **お題エンジン(本プラン)** — predicates / topic_catalog / topic_types / topic_generator
3. プレイ照合 + セッション管理 — play_matcher / session_manager
4. 盤面描画 — board(Pillow)
5. bot 基盤 / 6. スラッシュコマンド cogs

**スコープ境界(意図的):**
- **本プランは「生成」まで。** プレイ申告の照合・進捗加算(`play_matcher`)と SUM 型の累積値抽出は Plan 3。本プランは Topic に `progress_kind`(COUNT/SUM)と `required`(閾値)を持たせるだけで、累積ロジックは書かない(YAGNI)。
- **述語 `predicates.py` は本プランで全 25 型を実装する。** 生成の達成可能性検証で全型が必要であり、Plan 3 はこれを消費するだけにするため。

## File Structure

- Modify: `src/game/models.py` — `TopicType` / `PlayCondition` / `ProgressKind` / `FilterValue` / `Topic` を追記
- Create: `src/game/predicates.py` — 型ごとの楽曲フィルタ述語と `PREDICATE_BUILDERS` レジストリ
- Create: `src/game/topic_catalog.py` — `all_topics.json` を `TopicTemplate` へ読込
- Create: `src/game/topic_types.py` — 型ごとの進捗種別・value 整形の `TYPE_INFO` レジストリ
- Create: `src/game/topic_generator.py` — set/value/プレイ種別抽選 + 達成可能性検証で Topic を生成
- Create: `tests/game/test_predicates.py` — 述語のテーブル駆動テスト
- Create: `tests/game/test_topic_catalog.py` — テンプレート読込テスト
- Create: `tests/game/test_topic_types.py` — レジストリ網羅・整形テスト
- Create: `tests/game/test_topic_generator.py` — 生成(件数・達成可能性・分布・パネル番号)テスト
- Create: `tests/game/test_topic_generator_integration.py` — 実データでの生成検証

---

## Task 1: お題モデル(TopicType / PlayCondition / ProgressKind / Topic)

お題に必要な列挙とデータレコードを `models.py` に追加する。`Topic.progress` / `completed` はプレイ進行で更新されるため frozen にしない。

**Files:**
- Modify: `src/game/models.py`
- Test: `tests/game/test_models.py`(追記)

- [ ] **Step 1: 失敗するテストを追記**

Append to `tests/game/test_models.py`:

```python
from src.game.models import (
    PlayCondition,
    ProgressKind,
    Topic,
    TopicType,
)


def test_topic_construction_defaults() -> None:
    topic = Topic(
        panel_no=1,
        topic_type=TopicType.TITLE_INCLUDE,
        play_condition=PlayCondition.PLAY,
        filter_value=("a", "c"),
        required=3,
        progress_kind=ProgressKind.COUNT,
        description="楽曲名に(a, c)のすべてが含まれる楽曲を3回play",
    )
    assert topic.progress == 0
    assert topic.completed is False
    assert TopicType("title_include") is TopicType.TITLE_INCLUDE
    assert PlayCondition.FULL_COMBO.value == "FC"
    assert ProgressKind.SUM.value == "SUM"


def test_topic_progress_is_mutable() -> None:
    topic = Topic(
        panel_no=2,
        topic_type=TopicType.LEVEL_TOTAL,
        play_condition=PlayCondition.ALL_CHARMING,
        filter_value=None,
        required=40,
        progress_kind=ProgressKind.SUM,
        description="ACした譜面のレベルの合計が40",
    )
    topic.progress += 8
    topic.completed = True
    assert topic.progress == 8
    assert topic.completed is True
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `uv run pytest tests/game/test_models.py -k topic -v`
Expected: FAIL(`ImportError: cannot import name 'TopicType'`)

- [ ] **Step 3: モデルを追記**

Append to `src/game/models.py`:

```python
class TopicType(str, Enum):
    """お題テンプレートの型。値は all_topics.json の type と一致させる。"""

    TITLE_INCLUDE = "title_include"
    TITLE_STARTSWITH = "title_startswith"
    TITLE_ENDSWITH = "title_endswith"
    TITLE_LEN_BELOW = "title_len_below"
    TITLE_LEN_ABOVE = "title_len_above"
    TITLE_BLANK = "title_blank"
    DIFFICULT = "difficult"
    LEVEL = "level"
    LEVEL_TOTAL = "level_total"
    RESULT_CHARMING_TOTAL = "result_charming_total"
    RESULT_COMBO_TOTAL = "result_combo_total"
    NOTES_BELOW = "notes_below"
    NOTES_ABOVE = "notes_above"
    NOTES_DENSITY_BELOW = "notes_density_below"
    NOTES_DENSITY_ABOVE = "notes_density_above"
    NOTES_ENDSWITH = "notes_endswith"
    COMPOSER_NAME_STARTSWITH = "composer_name_startswith"
    COMPOSER_NAME_ENDSWITH = "composer_name_endswith"
    COMPOSER_MEMBERS = "composer_members"
    FEATURING = "featuring"
    TIME_BELOW = "time_below"
    TIME_ABOVE = "time_above"
    VERSION = "version"
    BOOK = "book"
    SHELF = "shelf"


class PlayCondition(str, Enum):
    """お題達成に要するプレイ種別。値は説明文の置換語にも使う。"""

    PLAY = "play"
    FULL_COMBO = "FC"
    ALL_CHARMING = "AC"


class ProgressKind(str, Enum):
    """進捗の数え方。COUNT=条件一致プレイの回数、SUM=申告値の累積。"""

    COUNT = "COUNT"
    SUM = "SUM"


# 解決済みフィルタ値。candidate 系は選んだ文字/候補の組、range 系は数値、null 型は None。
FilterValue = tuple[str, ...] | int | float | None


@dataclass
class Topic:
    """生成済みの 1 お題。progress/completed はプレイ進行で更新するため frozen にしない。"""

    panel_no: int
    topic_type: TopicType
    play_condition: PlayCondition
    filter_value: FilterValue
    required: int
    progress_kind: ProgressKind
    description: str
    progress: int = 0
    completed: bool = False
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `uv run pytest tests/game/test_models.py -v`
Expected: PASS(既存 + 追加分すべて)

- [ ] **Step 5: コミット**

```bash
git add src/game/models.py tests/game/test_models.py
git commit -m "feat: お題モデル(TopicType/PlayCondition/ProgressKind/Topic)を追加" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: 楽曲フィルタ述語(predicates.py、全 25 型)

型ごとに「解決済み値 → `(Song, Difficulty) -> bool` 述語」を作るビルダーを定義し、`@_register` で `PREDICATE_BUILDERS` に自己登録する。生成の達成可能性検証と Plan 3 の照合が同じ述語を共有する。`difficult` のみ申告難易度を使い、他は楽曲属性のみ参照する(設計の述語一覧に忠実)。

**Files:**
- Create: `src/game/predicates.py`
- Test: `tests/game/test_predicates.py`

- [ ] **Step 1: 失敗するテストを書く**

Create `tests/game/test_predicates.py`:

```python
from src.game.models import Chart, Difficulty, Song, TopicType
from src.game.predicates import PREDICATE_BUILDERS, FilterValue


def _song(
    *,
    title: str = "X",
    composers: tuple[str, ...] = ("C",),
    featuring: tuple[str, ...] = (),
    time: int = 100,
    version: str = "1.0",
    book: str = "B",
    shelf: str = "S",
    charts: dict[Difficulty, Chart] | None = None,
) -> Song:
    if charts is None:
        charts = {Difficulty.HARD: Chart(level=8, notes=485)}
    return Song(
        title=title,
        shelf=shelf,
        book=book,
        version=version,
        charts=charts,
        time=time,
        composers=composers,
        featuring=featuring,
        image_path=None,
    )


def _check(topic_type: TopicType, value: FilterValue, song: Song, difficulty: Difficulty) -> bool:
    return PREDICATE_BUILDERS[topic_type](value)(song, difficulty)


def test_all_types_registered() -> None:
    assert set(PREDICATE_BUILDERS) == set(TopicType)


def test_title_predicates() -> None:
    d = Difficulty.HARD
    assert _check(TopicType.TITLE_INCLUDE, ("a", "e"), _song(title="Daybreak"), d)
    assert not _check(TopicType.TITLE_INCLUDE, ("a", "z"), _song(title="Daybreak"), d)
    assert _check(TopicType.TITLE_STARTSWITH, ("a", "d"), _song(title="Dream"), d)
    assert not _check(TopicType.TITLE_STARTSWITH, ("x", "y"), _song(title="Dream"), d)
    assert _check(TopicType.TITLE_ENDSWITH, ("a", "k"), _song(title="Saika"), d)
    assert _check(TopicType.TITLE_LEN_BELOW, 5, _song(title="Aya"), d)
    assert not _check(TopicType.TITLE_LEN_BELOW, 2, _song(title="Aya"), d)
    assert _check(TopicType.TITLE_LEN_ABOVE, 3, _song(title="Aya"), d)
    assert _check(TopicType.TITLE_BLANK, 2, _song(title="a b c"), d)
    assert not _check(TopicType.TITLE_BLANK, 1, _song(title="a b c"), d)


def test_difficulty_and_level_predicates() -> None:
    charts = {
        Difficulty.EASY: Chart(level=1, notes=78),
        Difficulty.HARD: Chart(level=8, notes=485),
    }
    assert _check(TopicType.DIFFICULT, ("Hard",), _song(charts=charts), Difficulty.HARD)
    assert not _check(TopicType.DIFFICULT, ("Hard",), _song(charts=charts), Difficulty.EASY)
    assert _check(TopicType.LEVEL, 8, _song(charts=charts), Difficulty.EASY)
    assert not _check(TopicType.LEVEL, 12, _song(charts=charts), Difficulty.EASY)


def test_sum_predicates_always_true() -> None:
    d = Difficulty.HARD
    for topic_type in (
        TopicType.LEVEL_TOTAL,
        TopicType.RESULT_COMBO_TOTAL,
        TopicType.RESULT_CHARMING_TOTAL,
    ):
        assert _check(topic_type, None, _song(), d)


def test_notes_predicates() -> None:
    d = Difficulty.HARD
    song = _song(time=100, charts={Difficulty.HARD: Chart(level=8, notes=480)})
    assert _check(TopicType.NOTES_BELOW, 500, song, d)
    assert not _check(TopicType.NOTES_BELOW, 100, song, d)
    assert _check(TopicType.NOTES_ABOVE, 400, song, d)
    assert _check(TopicType.NOTES_DENSITY_BELOW, 5.0, song, d)  # 480/100=4.8
    assert _check(TopicType.NOTES_DENSITY_ABOVE, 4.0, song, d)
    assert _check(TopicType.NOTES_ENDSWITH, ("0",), song, d)  # 480 末尾 0
    assert not _check(TopicType.NOTES_ENDSWITH, ("5",), song, d)


def test_composer_predicates() -> None:
    d = Difficulty.HARD
    assert _check(TopicType.COMPOSER_NAME_STARTSWITH, ("s", "r"), _song(composers=("Rabpit",)), d)
    assert _check(TopicType.COMPOSER_NAME_ENDSWITH, ("i",) , _song(composers=("Morrigan", "Rabpit")), d)
    assert _check(TopicType.COMPOSER_MEMBERS, None, _song(composers=("A", "B")), d)
    assert not _check(TopicType.COMPOSER_MEMBERS, None, _song(composers=("A",)), d)
    assert _check(TopicType.FEATURING, None, _song(featuring=("Singer",)), d)
    assert not _check(TopicType.FEATURING, None, _song(featuring=()), d)


def test_time_version_book_shelf_predicates() -> None:
    d = Difficulty.HARD
    song = _song(time=120, version="2.0", book="Etude", shelf="II")
    assert _check(TopicType.TIME_BELOW, 130, song, d)
    assert not _check(TopicType.TIME_BELOW, 100, song, d)
    assert _check(TopicType.TIME_ABOVE, 100, song, d)
    assert _check(TopicType.VERSION, ("1.0", "2.0"), song, d)
    assert not _check(TopicType.VERSION, ("1.0",), song, d)
    assert _check(TopicType.BOOK, ("Etude",), song, d)
    assert _check(TopicType.SHELF, ("II", "Story"), song, d)
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `uv run pytest tests/game/test_predicates.py -v`
Expected: FAIL(`ModuleNotFoundError: No module named 'src.game.predicates'`)

- [ ] **Step 3: predicates.py を実装**

Create `src/game/predicates.py`:

```python
from __future__ import annotations

from collections.abc import Callable
from typing import cast

from src.game.models import Difficulty, FilterValue, Song, TopicType

Predicate = Callable[[Song, Difficulty], bool]
PredicateBuilder = Callable[[FilterValue], Predicate]

PREDICATE_BUILDERS: dict[TopicType, PredicateBuilder] = {}


def _register(topic_type: TopicType) -> Callable[[PredicateBuilder], PredicateBuilder]:
    # 中央の辞書リテラルを編集せず型ごとに自己登録させ、型の追加を局所化する。
    def deco(builder: PredicateBuilder) -> PredicateBuilder:
        PREDICATE_BUILDERS[topic_type] = builder
        return builder

    return deco


def _chars(value: FilterValue) -> tuple[str, ...]:
    return cast(tuple[str, ...], value)


@_register(TopicType.TITLE_INCLUDE)
def _title_include(value: FilterValue) -> Predicate:
    chars = _chars(value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        title = song.title.casefold()
        return all(ch in title for ch in chars)

    return pred


@_register(TopicType.TITLE_STARTSWITH)
def _title_startswith(value: FilterValue) -> Predicate:
    chars = _chars(value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        return song.title.casefold().startswith(chars)

    return pred


@_register(TopicType.TITLE_ENDSWITH)
def _title_endswith(value: FilterValue) -> Predicate:
    chars = _chars(value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        return song.title.casefold().endswith(chars)

    return pred


@_register(TopicType.TITLE_LEN_BELOW)
def _title_len_below(value: FilterValue) -> Predicate:
    threshold = cast(int, value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        return len(song.title) <= threshold

    return pred


@_register(TopicType.TITLE_LEN_ABOVE)
def _title_len_above(value: FilterValue) -> Predicate:
    threshold = cast(int, value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        return len(song.title) >= threshold

    return pred


@_register(TopicType.TITLE_BLANK)
def _title_blank(value: FilterValue) -> Predicate:
    count = cast(int, value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        return song.title.count(" ") == count

    return pred


@_register(TopicType.DIFFICULT)
def _difficult(value: FilterValue) -> Predicate:
    allowed = _chars(value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        return difficulty.value in allowed

    return pred


@_register(TopicType.LEVEL)
def _level(value: FilterValue) -> Predicate:
    level = cast(int, value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        return any(chart.level == level for chart in song.charts.values())

    return pred


def _always_true(value: FilterValue) -> Predicate:
    # SUM 型はフィルタを持たず全プレイを累積対象にする。
    def pred(song: Song, difficulty: Difficulty) -> bool:
        return True

    return pred


PREDICATE_BUILDERS[TopicType.LEVEL_TOTAL] = _always_true
PREDICATE_BUILDERS[TopicType.RESULT_COMBO_TOTAL] = _always_true
PREDICATE_BUILDERS[TopicType.RESULT_CHARMING_TOTAL] = _always_true


@_register(TopicType.NOTES_BELOW)
def _notes_below(value: FilterValue) -> Predicate:
    threshold = cast(int, value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        return any(chart.notes <= threshold for chart in song.charts.values())

    return pred


@_register(TopicType.NOTES_ABOVE)
def _notes_above(value: FilterValue) -> Predicate:
    threshold = cast(int, value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        return any(chart.notes >= threshold for chart in song.charts.values())

    return pred


@_register(TopicType.NOTES_DENSITY_BELOW)
def _notes_density_below(value: FilterValue) -> Predicate:
    threshold = cast(float, value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        return any(chart.notes / song.time <= threshold for chart in song.charts.values())

    return pred


@_register(TopicType.NOTES_DENSITY_ABOVE)
def _notes_density_above(value: FilterValue) -> Predicate:
    threshold = cast(float, value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        return any(chart.notes / song.time >= threshold for chart in song.charts.values())

    return pred


@_register(TopicType.NOTES_ENDSWITH)
def _notes_endswith(value: FilterValue) -> Predicate:
    digits = _chars(value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        return any(str(chart.notes).endswith(digits) for chart in song.charts.values())

    return pred


@_register(TopicType.COMPOSER_NAME_STARTSWITH)
def _composer_name_startswith(value: FilterValue) -> Predicate:
    chars = _chars(value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        return any(name.casefold().startswith(chars) for name in song.composers)

    return pred


@_register(TopicType.COMPOSER_NAME_ENDSWITH)
def _composer_name_endswith(value: FilterValue) -> Predicate:
    chars = _chars(value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        return any(name.casefold().endswith(chars) for name in song.composers)

    return pred


@_register(TopicType.COMPOSER_MEMBERS)
def _composer_members(value: FilterValue) -> Predicate:
    def pred(song: Song, difficulty: Difficulty) -> bool:
        return len(song.composers) > 1

    return pred


@_register(TopicType.FEATURING)
def _featuring(value: FilterValue) -> Predicate:
    def pred(song: Song, difficulty: Difficulty) -> bool:
        return len(song.featuring) > 0

    return pred


@_register(TopicType.TIME_BELOW)
def _time_below(value: FilterValue) -> Predicate:
    threshold = cast(int, value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        return song.time <= threshold

    return pred


@_register(TopicType.TIME_ABOVE)
def _time_above(value: FilterValue) -> Predicate:
    threshold = cast(int, value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        return song.time >= threshold

    return pred


@_register(TopicType.VERSION)
def _version(value: FilterValue) -> Predicate:
    allowed = _chars(value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        return song.version in allowed

    return pred


@_register(TopicType.BOOK)
def _book(value: FilterValue) -> Predicate:
    allowed = _chars(value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        return song.book in allowed

    return pred


@_register(TopicType.SHELF)
def _shelf(value: FilterValue) -> Predicate:
    allowed = _chars(value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        return song.shelf in allowed

    return pred
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `uv run pytest tests/game/test_predicates.py -v`
Expected: PASS(7 件)

- [ ] **Step 5: コミット**

```bash
git add src/game/predicates.py tests/game/test_predicates.py
git commit -m "feat: 全25型の楽曲フィルタ述語を追加" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: お題テンプレートの読込(topic_catalog.py)

`all_topics.json`(リスト)を `TopicTemplate` へパースする。`value` は `null` / `{range:[...]}` / `{candidate, choice}` の 3 形を `ValueSpec` に正規化する。candidate は文字プール文字列・候補リスト・`version_list` などのトークンを取り得る。

**Files:**
- Create: `src/game/topic_catalog.py`
- Test: `tests/game/test_topic_catalog.py`

- [ ] **Step 1: 失敗するテストを書く**

Create `tests/game/test_topic_catalog.py`:

```python
import json
from pathlib import Path

from src.game.models import TopicType
from src.game.topic_catalog import (
    CandidateSpec,
    RangeSpec,
    TopicTemplate,
    load_topics,
)


def _write(tmp_path: Path) -> Path:
    data = [
        {
            "type": "title_include",
            "description": "楽曲名にvalueのすべてが含まれる楽曲をset回play",
            "set": [2, 4, 1],
            "value": {"candidate": "abcdefghijklmnopqrstuvwxyz", "choice": 2},
        },
        {
            "type": "difficult",
            "description": "難易度valueでset回play",
            "set": [3, 5, 1],
            "value": {"candidate": ["Easy", "Normal", "Hard"], "choice": 1},
        },
        {
            "type": "level",
            "description": "Lv.valueの譜面を持つ楽曲をset回play",
            "set": [3, 5, 1],
            "value": {"range": [1, 12, 1]},
        },
        {
            "type": "level_total",
            "description": "playした譜面のレベルの合計がset",
            "set": [30, 50, 10],
            "value": None,
        },
        {
            "type": "version",
            "description": "ver.valueに実装された楽曲をset回play",
            "set": [1, 3, 1],
            "value": {"candidate": "version_list", "choice": 3},
        },
    ]
    path = tmp_path / "all_topics.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_load_parses_all_value_shapes(tmp_path: Path) -> None:
    templates = load_topics(_write(tmp_path))
    by_type = {t.topic_type: t for t in templates}

    char_pool = by_type[TopicType.TITLE_INCLUDE]
    assert char_pool.set_spec == (2, 4, 1)
    assert isinstance(char_pool.value_spec, CandidateSpec)
    assert char_pool.value_spec.candidate == "abcdefghijklmnopqrstuvwxyz"
    assert char_pool.value_spec.choice == 2

    difficult = by_type[TopicType.DIFFICULT]
    assert isinstance(difficult.value_spec, CandidateSpec)
    assert difficult.value_spec.candidate == ("Easy", "Normal", "Hard")

    level = by_type[TopicType.LEVEL]
    assert isinstance(level.value_spec, RangeSpec)
    assert (level.value_spec.low, level.value_spec.high, level.value_spec.step) == (1, 12, 1)

    assert by_type[TopicType.LEVEL_TOTAL].value_spec is None

    version = by_type[TopicType.VERSION]
    assert isinstance(version.value_spec, CandidateSpec)
    assert version.value_spec.candidate == "version_list"


def test_returns_topic_template_instances(tmp_path: Path) -> None:
    templates = load_topics(_write(tmp_path))
    assert all(isinstance(t, TopicTemplate) for t in templates)
    assert len(templates) == 5
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `uv run pytest tests/game/test_topic_catalog.py -v`
Expected: FAIL(`ModuleNotFoundError: No module named 'src.game.topic_catalog'`)

- [ ] **Step 3: topic_catalog.py を実装**

Create `src/game/topic_catalog.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from src.game.models import TopicType


@dataclass(frozen=True)
class RangeSpec:
    """[low, high, step] の閉区間から数値を抽選するための指定。"""

    low: float
    high: float
    step: float


@dataclass(frozen=True)
class CandidateSpec:
    """候補から choice 個選ぶ指定。candidate は文字プール/候補リスト/派生一覧トークン。"""

    candidate: str | tuple[str, ...]
    choice: int


ValueSpec = RangeSpec | CandidateSpec | None


@dataclass(frozen=True)
class TopicTemplate:
    """お題 1 型のテンプレート。"""

    topic_type: TopicType
    description: str
    set_spec: tuple[int, int, int]
    value_spec: ValueSpec


def _parse_value(raw: object) -> ValueSpec:
    if raw is None:
        return None
    node = cast(dict[str, object], raw)
    if "range" in node:
        low, high, step = cast(list[float], node["range"])
        return RangeSpec(low=low, high=high, step=step)
    candidate = node["candidate"]
    choice = cast(int, node["choice"])
    if isinstance(candidate, list):
        return CandidateSpec(candidate=tuple(cast(list[str], candidate)), choice=choice)
    return CandidateSpec(candidate=cast(str, candidate), choice=choice)


def load_topics(topics_path: Path) -> list[TopicTemplate]:
    raw = cast(list[dict[str, object]], json.loads(topics_path.read_text(encoding="utf-8")))
    templates: list[TopicTemplate] = []
    for node in raw:
        set_min, set_max, set_step = cast(list[int], node["set"])
        templates.append(
            TopicTemplate(
                topic_type=TopicType(cast(str, node["type"])),
                description=cast(str, node["description"]),
                set_spec=(set_min, set_max, set_step),
                value_spec=_parse_value(node.get("value")),
            )
        )
    return templates
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `uv run pytest tests/game/test_topic_catalog.py -v`
Expected: PASS(2 件)

- [ ] **Step 5: コミット**

```bash
git add src/game/topic_catalog.py tests/game/test_topic_catalog.py
git commit -m "feat: お題テンプレートの読込を追加" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: 型メタデータと説明整形(topic_types.py)

型ごとの進捗種別(COUNT/SUM)と value 整形関数を `TYPE_INFO` に登録する。candidate 系の解決値は文字/候補の組なので「単一はそのまま、複数は `(a, b)`」で整形し、range 系の数値はそのまま文字列化する。説明文は `value`/`set`/`play` のトークンを順に置換する。

**Files:**
- Create: `src/game/topic_types.py`
- Test: `tests/game/test_topic_types.py`

- [ ] **Step 1: 失敗するテストを書く**

Create `tests/game/test_topic_types.py`:

```python
from src.game.models import FilterValue, PlayCondition, ProgressKind, TopicType
from src.game.topic_types import TYPE_INFO, format_description, format_value


def test_all_types_have_info() -> None:
    assert set(TYPE_INFO) == set(TopicType)


def test_sum_progress_kinds() -> None:
    sum_types = {
        TopicType.LEVEL_TOTAL,
        TopicType.RESULT_COMBO_TOTAL,
        TopicType.RESULT_CHARMING_TOTAL,
    }
    for topic_type in TopicType:
        expected = ProgressKind.SUM if topic_type in sum_types else ProgressKind.COUNT
        assert TYPE_INFO[topic_type].progress_kind is expected


def test_format_value_variants() -> None:
    assert format_value(TopicType.TITLE_INCLUDE, ("a", "c")) == "(a, c)"
    assert format_value(TopicType.NOTES_ENDSWITH, ("0",)) == "0"
    assert format_value(TopicType.DIFFICULT, ("Hard",)) == "Hard"
    assert format_value(TopicType.LEVEL, 8) == "8"
    assert format_value(TopicType.NOTES_DENSITY_ABOVE, 1.2) == "1.2"


def test_format_description_replaces_tokens() -> None:
    text = format_description(
        topic_type=TopicType.TITLE_INCLUDE,
        description="楽曲名にvalueのすべてが含まれる楽曲をset回play",
        value=("a", "c"),
        required=3,
        play_condition=PlayCondition.FULL_COMBO,
    )
    assert text == "楽曲名に(a, c)のすべてが含まれる楽曲を3回FC"


def test_format_description_sum_without_value_token() -> None:
    text = format_description(
        topic_type=TopicType.LEVEL_TOTAL,
        description="playした譜面のレベルの合計がset",
        value=None,
        required=40,
        play_condition=PlayCondition.PLAY,
    )
    assert text == "playした譜面のレベルの合計が40"
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `uv run pytest tests/game/test_topic_types.py -v`
Expected: FAIL(`ModuleNotFoundError: No module named 'src.game.topic_types'`)

- [ ] **Step 3: topic_types.py を実装**

Create `src/game/topic_types.py`:

```python
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from src.game.models import FilterValue, PlayCondition, ProgressKind, TopicType

ValueFormatter = Callable[[FilterValue], str]


def _format_chars(value: FilterValue) -> str:
    # candidate 系の解決値。単一はそのまま、複数は説明用に "(a, b)" で並べる。
    chars = cast(tuple[str, ...], value)
    if len(chars) == 1:
        return chars[0]
    return "(" + ", ".join(chars) + ")"


def _format_scalar(value: FilterValue) -> str:
    return str(value)


@dataclass(frozen=True)
class TypeInfo:
    """型ごとの進捗種別と value 整形担当。"""

    progress_kind: ProgressKind
    value_formatter: ValueFormatter


_SUM_TYPES = {
    TopicType.LEVEL_TOTAL,
    TopicType.RESULT_COMBO_TOTAL,
    TopicType.RESULT_CHARMING_TOTAL,
}

_CHAR_TYPES = {
    TopicType.TITLE_INCLUDE,
    TopicType.TITLE_STARTSWITH,
    TopicType.TITLE_ENDSWITH,
    TopicType.DIFFICULT,
    TopicType.NOTES_ENDSWITH,
    TopicType.COMPOSER_NAME_STARTSWITH,
    TopicType.COMPOSER_NAME_ENDSWITH,
    TopicType.VERSION,
    TopicType.BOOK,
    TopicType.SHELF,
}


def _build_type_info() -> dict[TopicType, TypeInfo]:
    info: dict[TopicType, TypeInfo] = {}
    for topic_type in TopicType:
        progress_kind = ProgressKind.SUM if topic_type in _SUM_TYPES else ProgressKind.COUNT
        formatter = _format_chars if topic_type in _CHAR_TYPES else _format_scalar
        info[topic_type] = TypeInfo(progress_kind=progress_kind, value_formatter=formatter)
    return info


TYPE_INFO = _build_type_info()


def format_value(topic_type: TopicType, value: FilterValue) -> str:
    return TYPE_INFO[topic_type].value_formatter(value)


def format_description(
    *,
    topic_type: TopicType,
    description: str,
    value: FilterValue,
    required: int,
    play_condition: PlayCondition,
) -> str:
    # value→set→play の順で置換する。整形後の value/required は set/play を再導入しない。
    text = description
    if "value" in text:
        text = text.replace("value", format_value(topic_type, value))
    text = text.replace("set", str(required))
    return text.replace("play", play_condition.value)
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `uv run pytest tests/game/test_topic_types.py -v`
Expected: PASS(5 件)

- [ ] **Step 5: コミット**

```bash
git add src/game/topic_types.py tests/game/test_topic_types.py
git commit -m "feat: 型メタデータと説明整形を追加" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: お題生成(topic_generator.py)

テンプレ 1 件から「set 抽選 → value 解決 → プレイ種別抽選 → 達成可能性検証」を回し、実在曲が 1 件以上一致するまで再抽選して Topic を 1 個作る。乱数は `random.Random` を注入してテスト可能にする。

**Files:**
- Create: `src/game/topic_generator.py`
- Test: `tests/game/test_topic_generator.py`

- [ ] **Step 1: 失敗するテストを書く**

Create `tests/game/test_topic_generator.py`:

```python
import random

from src.game.models import (
    Chart,
    Difficulty,
    PlayCondition,
    ProgressKind,
    Song,
    TopicType,
)
from src.game.song_repository import SongRepository
from src.game.topic_catalog import CandidateSpec, RangeSpec, TopicTemplate
from src.game.topic_generator import generate_topic


def _repo() -> SongRepository:
    songs = [
        Song(
            title="Dream",
            shelf="Story",
            book="Vol.1A",
            version="1.0",
            charts={Difficulty.EASY: Chart(level=1, notes=78), Difficulty.HARD: Chart(level=8, notes=485)},
            time=133,
            composers=("Rabpit",),
            featuring=(),
            image_path=None,
        ),
        Song(
            title="Saika",
            shelf="II",
            book="Etude",
            version="2.0",
            charts={Difficulty.HARD: Chart(level=9, notes=600)},
            time=120,
            composers=("Morrigan", "Cranky"),
            featuring=(),
            image_path=None,
        ),
    ]
    return SongRepository(songs)


def test_generate_topic_is_achievable_and_formatted() -> None:
    template = TopicTemplate(
        topic_type=TopicType.LEVEL,
        description="Lv.valueの譜面を持つ楽曲をset回play",
        set_spec=(3, 5, 1),
        value_spec=RangeSpec(low=1, high=12, step=1),
    )
    rng = random.Random(0)
    topic = generate_topic(template, panel_no=4, repo=_repo(), rng=rng)

    assert topic.panel_no == 4
    assert topic.topic_type is TopicType.LEVEL
    assert 3 <= topic.required <= 5
    assert topic.progress_kind is ProgressKind.COUNT
    assert topic.progress == 0 and topic.completed is False
    # 解決値で実在曲が一致する(達成可能)。
    songs = _repo().songs
    assert any(chart.level == topic.filter_value for s in songs for chart in s.charts.values())
    # 説明に未置換トークンが残らない。
    assert "value" not in topic.description and "set" not in topic.description


def test_generate_topic_play_condition_distribution() -> None:
    template = TopicTemplate(
        topic_type=TopicType.SHELF,
        description="value棚に収録されている楽曲をset回play",
        set_spec=(3, 5, 1),
        value_spec=CandidateSpec(candidate="shelf_list", choice=1),
    )
    rng = random.Random(1)
    repo = _repo()
    conditions = [
        generate_topic(template, panel_no=1, repo=repo, rng=rng).play_condition
        for _ in range(200)
    ]
    play = conditions.count(PlayCondition.PLAY)
    # 60% 前後に寄る(おおまかな分布確認)。
    assert 100 < play < 160


def test_generate_topic_sum_type() -> None:
    template = TopicTemplate(
        topic_type=TopicType.LEVEL_TOTAL,
        description="playした譜面のレベルの合計がset",
        set_spec=(30, 50, 10),
        value_spec=None,
    )
    topic = generate_topic(template, panel_no=2, repo=_repo(), rng=random.Random(0))
    assert topic.progress_kind is ProgressKind.SUM
    assert topic.filter_value is None
    assert topic.required in (30, 40, 50)
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `uv run pytest tests/game/test_topic_generator.py -v`
Expected: FAIL(`ModuleNotFoundError: No module named 'src.game.topic_generator'`)

- [ ] **Step 3: topic_generator.py を実装(単体生成まで)**

Create `src/game/topic_generator.py`:

```python
from __future__ import annotations

import random

from src.game.models import FilterValue, PlayCondition, Song, Topic, TopicType
from src.game.predicates import PREDICATE_BUILDERS, Predicate
from src.game.song_repository import SongRepository
from src.game.topic_catalog import CandidateSpec, RangeSpec, TopicTemplate, ValueSpec
from src.game.topic_types import TYPE_INFO, format_description

# 達成可能な value が見つからない場合の無限ループ防止。実データでは十分余裕がある。
_MAX_ATTEMPTS = 200


def _stepped_values(spec: RangeSpec) -> list[int | float]:
    count = round((spec.high - spec.low) / spec.step)
    values = [round(spec.low + i * spec.step, 6) for i in range(count + 1)]
    if all(float(v).is_integer() for v in values):
        return [int(v) for v in values]
    return values


def _candidate_pool(candidate: str | tuple[str, ...], repo: SongRepository) -> list[str]:
    if candidate == "version_list":
        return repo.versions()
    if candidate == "book_list":
        return repo.books()
    if candidate == "shelf_list":
        return repo.shelves()
    if isinstance(candidate, tuple):
        return list(candidate)
    return list(candidate)


def _resolve_value(spec: ValueSpec, repo: SongRepository, rng: random.Random) -> FilterValue:
    if spec is None:
        return None
    if isinstance(spec, RangeSpec):
        return rng.choice(_stepped_values(spec))
    pool = _candidate_pool(spec.candidate, repo)
    return tuple(sorted(rng.sample(pool, spec.choice)))


def _roll_required(set_spec: tuple[int, int, int], rng: random.Random) -> int:
    set_min, set_max, set_step = set_spec
    return rng.choice(list(range(set_min, set_max + 1, set_step)))


def _roll_play_condition(rng: random.Random) -> PlayCondition:
    roll = rng.random()
    if roll < 0.6:
        return PlayCondition.PLAY
    if roll < 0.9:
        return PlayCondition.FULL_COMBO
    return PlayCondition.ALL_CHARMING


def _is_achievable(predicate: Predicate, songs: list[Song]) -> bool:
    return any(predicate(song, difficulty) for song in songs for difficulty in song.charts)


def generate_topic(
    template: TopicTemplate,
    panel_no: int,
    repo: SongRepository,
    rng: random.Random,
) -> Topic:
    info = TYPE_INFO[template.topic_type]
    builder = PREDICATE_BUILDERS[template.topic_type]
    songs = repo.songs
    for _ in range(_MAX_ATTEMPTS):
        required = _roll_required(template.set_spec, rng)
        value = _resolve_value(template.value_spec, repo, rng)
        play_condition = _roll_play_condition(rng)
        if not _is_achievable(builder(value), songs):
            continue
        description = format_description(
            topic_type=template.topic_type,
            description=template.description,
            value=value,
            required=required,
            play_condition=play_condition,
        )
        return Topic(
            panel_no=panel_no,
            topic_type=template.topic_type,
            play_condition=play_condition,
            filter_value=value,
            required=required,
            progress_kind=info.progress_kind,
            description=description,
        )
    raise RuntimeError(f"達成可能なお題を生成できません: {template.topic_type.value}")
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `uv run pytest tests/game/test_topic_generator.py -v`
Expected: PASS(3 件)

- [ ] **Step 5: コミット**

```bash
git add src/game/topic_generator.py tests/game/test_topic_generator.py
git commit -m "feat: お題の単体生成(達成可能性検証付き)を追加" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: N 個生成と実データ結合テスト

テンプレートをできるだけ型重複なく N 個選び(N > 型数なら重複許可)、パネル番号 1..N を振って Topic 群を返す。最後に実データ(`all_songs.json` / `all_topics.json`)で生成が機能し、全お題が達成可能であることを検証する。

**Files:**
- Modify: `src/game/topic_generator.py`(`generate_topics` を追加)
- Test: `tests/game/test_topic_generator.py`(追記)
- Test: `tests/game/test_topic_generator_integration.py`

- [ ] **Step 1: 失敗するテストを追記**

Append to `tests/game/test_topic_generator.py`:

```python
from src.game.topic_generator import generate_topics


def _templates() -> list[TopicTemplate]:
    return [
        TopicTemplate(
            topic_type=TopicType.LEVEL,
            description="Lv.valueの譜面を持つ楽曲をset回play",
            set_spec=(3, 5, 1),
            value_spec=RangeSpec(low=1, high=9, step=1),
        ),
        TopicTemplate(
            topic_type=TopicType.SHELF,
            description="value棚に収録されている楽曲をset回play",
            set_spec=(3, 5, 1),
            value_spec=CandidateSpec(candidate="shelf_list", choice=1),
        ),
    ]


def test_generate_topics_assigns_sequential_panels() -> None:
    topics = generate_topics(_templates(), count=2, repo=_repo(), rng=random.Random(0))
    assert [t.panel_no for t in topics] == [1, 2]
    assert {t.topic_type for t in topics} == {TopicType.LEVEL, TopicType.SHELF}


def test_generate_topics_allows_duplicates_when_count_exceeds_types() -> None:
    topics = generate_topics(_templates(), count=5, repo=_repo(), rng=random.Random(0))
    assert len(topics) == 5
    assert [t.panel_no for t in topics] == [1, 2, 3, 4, 5]
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `uv run pytest tests/game/test_topic_generator.py -k generate_topics -v`
Expected: FAIL(`ImportError: cannot import name 'generate_topics'`)

- [ ] **Step 3: generate_topics を追加**

Append to `src/game/topic_generator.py`:

```python
def _choose_templates(
    templates: list[TopicTemplate],
    count: int,
    rng: random.Random,
) -> list[TopicTemplate]:
    if count <= len(templates):
        return rng.sample(templates, count)
    # 型数を超える分は重複を許して補い、並びを混ぜる。
    chosen = list(templates)
    chosen += [rng.choice(templates) for _ in range(count - len(templates))]
    rng.shuffle(chosen)
    return chosen


def generate_topics(
    templates: list[TopicTemplate],
    count: int,
    repo: SongRepository,
    rng: random.Random,
) -> list[Topic]:
    chosen = _choose_templates(templates, count, rng)
    return [
        generate_topic(template, panel_no=index + 1, repo=repo, rng=rng)
        for index, template in enumerate(chosen)
    ]
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `uv run pytest tests/game/test_topic_generator.py -v`
Expected: PASS(5 件)

- [ ] **Step 5: 実データ結合テストを書く**

Create `tests/game/test_topic_generator_integration.py`:

```python
import random
from pathlib import Path

from src.game.predicates import PREDICATE_BUILDERS
from src.game.song_repository import SongRepository
from src.game.topic_catalog import load_topics
from src.game.topic_generator import generate_topics

ASSETS = Path(__file__).resolve().parents[2] / "assets"


def test_real_data_generates_achievable_topics() -> None:
    repo = SongRepository.from_files(
        ASSETS / "data" / "all_songs.json",
        ASSETS / "images",
    )
    templates = load_topics(ASSETS / "data" / "all_topics.json")
    songs = repo.songs

    topics = generate_topics(templates, count=9, repo=repo, rng=random.Random(42))

    assert [t.panel_no for t in topics] == list(range(1, 10))
    for topic in topics:
        assert topic.description
        assert "value" not in topic.description
        predicate = PREDICATE_BUILDERS[topic.topic_type](topic.filter_value)
        assert any(
            predicate(song, difficulty) for song in songs for difficulty in song.charts
        ), f"達成不能なお題が生成された: {topic.topic_type.value}"
```

- [ ] **Step 6: テストを実行して成功を確認**

Run: `uv run pytest tests/game/test_topic_generator_integration.py -v`
Expected: PASS(失敗する場合は実データのスキーマ差や述語の取りこぼしを調査)

- [ ] **Step 7: 全テストを実行**

Run: `uv run pytest -v`
Expected: 既存の楽曲データ層・config テストと本プランの全テストが PASS

- [ ] **Step 8: コミット**

```bash
git add src/game/topic_generator.py tests/game/test_topic_generator.py tests/game/test_topic_generator_integration.py
git commit -m "feat: お題のN個生成と実データ結合テストを追加" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage(お題エンジン M2 範囲):**
- 「テンプレートを選ぶ(型重複回避、N>型数で重複許可)」→ Task 6 `_choose_templates` ✓
- 「set から閾値/必要回数を抽選」→ Task 5 `_roll_required` ✓
- 「value 解決(null / range / candidate、version_list/book_list/shelf_list 導出)」→ Task 5 `_resolve_value` + `_candidate_pool`(Plan 1 の `versions/books/shelves` を利用)✓
- 「プレイ種別抽選(プレイ60/FC30/AC10、COUNT・SUM とも)」→ Task 5 `_roll_play_condition`(SUM 型も同経路)✓
- 「達成可能性検証(実在曲が1件以上)」→ Task 5 `_is_achievable` ✓
- 「description の value/set/play 整形」→ Task 4 `format_description` ✓
- 「型ごとの述語(title/difficult/level/notes/density/composer/featuring/time/version/book/shelf + SUM)」→ Task 2 全 25 型 ✓
- 「進捗種別 COUNT/SUM」→ Task 4 `TYPE_INFO.progress_kind`(Topic に保持)✓
- **照合・SUM 累積(play_matcher)** → Plan 3 へ意図的に後回し。本プランは述語と progress_kind/required の保持まで。

**2. Placeholder scan:** プレースホルダなし。全ステップに実コード/実コマンドあり。

**3. Type consistency:**
- `FilterValue = tuple[str, ...] | int | float | None` を models で定義し、predicates / topic_types / topic_generator で一貫使用。candidate 系の解決値は常に `tuple[str, ...]`(述語の `startswith/endswith` がタプルを受ける前提・`in` 判定とも整合)。
- `Predicate = Callable[[Song, Difficulty], bool]` / `PredicateBuilder = Callable[[FilterValue], Predicate]` を Task 2 で定義し Task 5 の `_is_achievable` と結合テストで再利用。
- `TopicTemplate`(topic_type, description, set_spec, value_spec)/ `RangeSpec(low, high, step)`/ `CandidateSpec(candidate, choice)` を Task 3 で定義し Task 5/6 で同名参照。
- `generate_topic(template, panel_no, repo, rng)` と `generate_topics(templates, count, repo, rng)` の引数名・順序が Task 5/6 で一致。
- `Topic` フィールド(panel_no, topic_type, play_condition, filter_value, required, progress_kind, description, progress=0, completed=False)が Task 1 定義と生成箇所で一致。

**4. 規約:** 型ヒント必須・`Any` 不使用(JSON 境界とフィルタ値は `cast`)・コメントは WHY のみ・docstring はテンプレート様式踏襲・関数は単一責務・乱数は注入でテスト可能。

**5. 既知の割り切り(WHY):**
- 説明整形はトークン置換方式(設計準拠)。整形後の value/required が `set`/`play` を再導入しない前提で value→set→play の順に置換する。
- `difficult` 以外の述語は申告難易度を参照しない(設計の述語定義「曲が条件を満たす」に忠実)。`difficult` のみ申告難易度と一致判定する。
- `_MAX_ATTEMPTS` は無限ループ防止の保険。実データでは達成可能な value が容易に見つかる。
