# Song Data Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `all_songs.json` を読み込み、部分一致検索・画像解決・派生一覧を提供する Discord 非依存の楽曲データ層を作る。

**Architecture:** 不変 dataclass(Song/Chart/Difficulty)へマスターデータをパースする純粋ロジック。`SongRepository` が検索・画像有無・棚/ブック/version 一覧を提供する。Discord も Pillow も使わず pytest で完結する。

**Tech Stack:** Python 3.12 / 標準ライブラリ(json, unicodedata, pathlib, enum, dataclasses)/ pytest。新規依存なし。

---

## このプランの位置づけ(全体ロードマップ)

設計([docs/superpowers/specs/2026-06-04-deemo-attack25-bot-design.md](docs/superpowers/specs/2026-06-04-deemo-attack25-bot-design.md))は規模が大きいため、サブシステムごとにプランを分割する。依存順:

1. **楽曲データ層(本プラン)** — models / song_repository
2. お題エンジン — topic_catalog / topic_types(レジストリ)/ topic_generator
3. プレイ照合 + セッション管理 — play_matcher / session_manager
4. 盤面描画 — board(Pillow)
5. bot 基盤 — config 拡張 / discord ログハンドラ / client / cog ローダ
6. スラッシュコマンド cogs + 端から端まで結線 + アーカイブ

各プランは単体で動作・テスト可能。本プランは全ての土台となる純粋ロジック。

**スコープ外(意図的な後回し):** ノーツ密度などお題述語専用の派生値は、それを使う Plan 2(お題エンジン)で定義する(YAGNI)。

## File Structure

- Create: `src/game/__init__.py` — game パッケージ初期化(空)
- Create: `src/game/models.py` — Difficulty / Chart / Song の dataclass(全プラン共有の中核モデル)
- Create: `src/game/song_repository.py` — 読込関数 `load_songs` と `SongRepository`(検索・画像・一覧)
- Create: `tests/game/__init__.py` — テストパッケージ初期化(空)
- Create: `tests/game/conftest.py` — テスト用の小さな楽曲データ/画像を用意する `song_assets` フィクスチャ
- Create: `tests/game/test_models.py` — モデル構築のテスト
- Create: `tests/game/test_song_repository.py` — 読込・検索・画像・一覧のテスト
- Create: `tests/game/test_song_repository_integration.py` — 実マスターデータでの読込検証

---

## Task 1: 中核モデル(Difficulty / Chart / Song)

**Files:**
- Create: `src/game/__init__.py`
- Create: `tests/game/__init__.py`
- Create: `src/game/models.py`
- Test: `tests/game/test_models.py`

- [ ] **Step 1: パッケージ初期化ファイルを作る**

`src/game/__init__.py` と `tests/game/__init__.py` を**空ファイル**として作成する(既存 `tests/__init__.py` と同様)。

- [ ] **Step 2: 失敗するテストを書く**

Create `tests/game/test_models.py`:

```python
from src.game.models import Chart, Difficulty, Song


def test_song_construction() -> None:
    song = Song(
        title="Dream",
        shelf="Story",
        book="Deemo's collection Vol.1A",
        version="1.0",
        charts={Difficulty.HARD: Chart(level=8, notes=485)},
        time=133,
        composers=("Rabpit",),
        featuring=(),
        image_path=None,
    )
    assert song.charts[Difficulty.HARD].notes == 485
    assert song.featuring == ()
    assert Difficulty.EASY.value == "Easy"
```

- [ ] **Step 3: テストを実行して失敗を確認**

Run: `uv run pytest tests/game/test_models.py -v`
Expected: FAIL(`ModuleNotFoundError: No module named 'src.game.models'`)

- [ ] **Step 4: 最小実装を書く**

Create `src/game/models.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class Difficulty(str, Enum):
    """譜面の難易度。値は all_songs.json の LEVEL/NOTES のキーと一致させる。"""

    EASY = "Easy"
    NORMAL = "Normal"
    HARD = "Hard"


@dataclass(frozen=True)
class Chart:
    """1 つの難易度に対する譜面情報。"""

    level: int
    notes: int


@dataclass(frozen=True)
class Song:
    """1 楽曲のマスターデータ。"""

    title: str
    shelf: str
    book: str
    version: str
    charts: dict[Difficulty, Chart]
    time: int
    composers: tuple[str, ...]
    featuring: tuple[str, ...]
    image_path: Path | None
```

- [ ] **Step 5: テストを実行して成功を確認**

Run: `uv run pytest tests/game/test_models.py -v`
Expected: PASS

- [ ] **Step 6: コミット**

```bash
git add src/game/__init__.py src/game/models.py tests/game/__init__.py tests/game/test_models.py
git commit -m "feat: 楽曲データ層の中核モデルを追加" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: マスターデータ読込(load_songs)

ネスト構造(棚 → ブック → 楽曲 → 属性)をパースし、featuring・複数作曲者・難易度欠落・画像解決を処理する。

**Files:**
- Create: `tests/game/conftest.py`
- Create: `src/game/song_repository.py`
- Test: `tests/game/test_song_repository.py`

- [ ] **Step 1: テスト用フィクスチャを作る**

Create `tests/game/conftest.py`:

```python
import json
from pathlib import Path

import pytest


@pytest.fixture
def song_assets(tmp_path: Path) -> tuple[Path, Path]:
    # 読込ロジックを実データに依存せず検証するため、小さなマスターデータと画像を用意する。
    # Pulses=featuring / Futarimiti=複数作曲者 / Saika=Normal 欠落 / 画像は Dream と Futarimiti のみ。
    data = {
        "Story": {
            "Deemo's collection Vol.1A": {
                "Dream": {
                    "VERSION": "1.0",
                    "LEVEL": {"Easy": 1, "Normal": 4, "Hard": 8},
                    "NOTES": {"Easy": 78, "Normal": 313, "Hard": 485},
                    "TIME": 133,
                    "COMPOSER": ["Rabpit"],
                },
                "Pulses": {
                    "VERSION": "1.0",
                    "LEVEL": {"Easy": 1, "Normal": 6, "Hard": 8},
                    "NOTES": {"Easy": 137, "Normal": 403, "Hard": 569},
                    "TIME": 123,
                    "COMPOSER": ["Sta"],
                    "feat.": ["A"],
                },
            }
        },
        "II": {
            "Etude": {
                "Futarimiti": {
                    "VERSION": "2.3",
                    "LEVEL": {"Easy": 3, "Normal": 6, "Hard": 8},
                    "NOTES": {"Easy": 236, "Normal": 433, "Hard": 783},
                    "TIME": 145,
                    "COMPOSER": ["Morrigan", "Cranky"],
                },
                "Saika": {
                    "VERSION": "2.0",
                    "LEVEL": {"Easy": 2, "Hard": 9},
                    "NOTES": {"Easy": 150, "Hard": 600},
                    "TIME": 120,
                    "COMPOSER": ["X"],
                },
            }
        },
    }
    songs_path = tmp_path / "all_songs.json"
    songs_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    images_dir = tmp_path / "images"
    images_dir.mkdir()
    (images_dir / "Dream.png").write_bytes(b"\x89PNG\r\n")
    (images_dir / "Futarimiti.png").write_bytes(b"\x89PNG\r\n")
    return songs_path, images_dir
```

- [ ] **Step 2: 失敗するテストを書く**

Create `tests/game/test_song_repository.py`:

```python
from pathlib import Path

from src.game.models import Difficulty
from src.game.song_repository import load_songs


def test_load_parses_basic_fields(song_assets: tuple[Path, Path]) -> None:
    songs_path, images_dir = song_assets
    by_title = {s.title: s for s in load_songs(songs_path, images_dir)}
    dream = by_title["Dream"]
    assert dream.shelf == "Story"
    assert dream.book == "Deemo's collection Vol.1A"
    assert dream.version == "1.0"
    assert dream.time == 133
    assert dream.composers == ("Rabpit",)


def test_featuring_detected(song_assets: tuple[Path, Path]) -> None:
    songs_path, images_dir = song_assets
    by_title = {s.title: s for s in load_songs(songs_path, images_dir)}
    assert by_title["Pulses"].featuring == ("A",)
    assert by_title["Dream"].featuring == ()


def test_multiple_composers(song_assets: tuple[Path, Path]) -> None:
    songs_path, images_dir = song_assets
    by_title = {s.title: s for s in load_songs(songs_path, images_dir)}
    assert by_title["Futarimiti"].composers == ("Morrigan", "Cranky")


def test_charts_built_and_missing_difficulty_skipped(
    song_assets: tuple[Path, Path],
) -> None:
    songs_path, images_dir = song_assets
    by_title = {s.title: s for s in load_songs(songs_path, images_dir)}
    dream = by_title["Dream"]
    assert dream.charts[Difficulty.HARD].notes == 485
    assert dream.charts[Difficulty.NORMAL].level == 4
    saika = by_title["Saika"]
    assert Difficulty.NORMAL not in saika.charts
    assert set(saika.charts) == {Difficulty.EASY, Difficulty.HARD}


def test_image_resolution(song_assets: tuple[Path, Path]) -> None:
    songs_path, images_dir = song_assets
    by_title = {s.title: s for s in load_songs(songs_path, images_dir)}
    assert by_title["Dream"].image_path == images_dir / "Dream.png"
    assert by_title["Pulses"].image_path is None
```

- [ ] **Step 3: テストを実行して失敗を確認**

Run: `uv run pytest tests/game/test_song_repository.py -v`
Expected: FAIL(`ImportError: cannot import name 'load_songs'`)

- [ ] **Step 4: 最小実装を書く**

Create `src/game/song_repository.py`:

```python
from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import cast

from src.game.models import Chart, Difficulty, Song


def _normalize(text: str) -> str:
    # 曲名とファイル名で Unicode 表現(NFC/NFD)が食い違っても突合できるよう正規化する。
    return unicodedata.normalize("NFC", text)


def _build_image_index(images_dir: Path) -> dict[str, Path]:
    index: dict[str, Path] = {}
    if images_dir.is_dir():
        for path in images_dir.glob("*.png"):
            index[_normalize(path.stem)] = path
    return index


def _parse_song(
    title: str,
    book: str,
    shelf: str,
    node: dict[str, object],
    image_index: dict[str, Path],
) -> Song:
    levels = cast(dict[str, int], node["LEVEL"])
    notes = cast(dict[str, int], node["NOTES"])
    charts: dict[Difficulty, Chart] = {}
    for difficulty in Difficulty:
        name = difficulty.value
        if name in levels and name in notes:
            charts[difficulty] = Chart(level=levels[name], notes=notes[name])
    return Song(
        title=title,
        shelf=shelf,
        book=book,
        version=str(node["VERSION"]),
        charts=charts,
        time=cast(int, node["TIME"]),
        composers=tuple(cast(list[str], node.get("COMPOSER", []))),
        featuring=tuple(cast(list[str], node.get("feat.", []))),
        image_path=image_index.get(_normalize(title)),
    )


def load_songs(songs_path: Path, images_dir: Path) -> list[Song]:
    raw = cast(
        dict[str, dict[str, dict[str, dict[str, object]]]],
        json.loads(songs_path.read_text(encoding="utf-8")),
    )
    image_index = _build_image_index(images_dir)
    songs: list[Song] = []
    for shelf, books in raw.items():
        for book, entries in books.items():
            for title, node in entries.items():
                songs.append(_parse_song(title, book, shelf, node, image_index))
    return songs
```

- [ ] **Step 5: テストを実行して成功を確認**

Run: `uv run pytest tests/game/test_song_repository.py -v`
Expected: PASS(5 件)

- [ ] **Step 6: コミット**

```bash
git add tests/game/conftest.py src/game/song_repository.py tests/game/test_song_repository.py
git commit -m "feat: all_songs.json の読込パーサを追加" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: 部分一致検索(SongRepository.search)

**Files:**
- Modify: `src/game/song_repository.py`(`SongRepository` クラスを追加)
- Test: `tests/game/test_song_repository.py`(検索テストを追記)

- [ ] **Step 1: 失敗するテストを追記**

Append to `tests/game/test_song_repository.py`:

```python
from src.game.song_repository import SongRepository


def test_search_is_partial_and_case_insensitive(
    song_assets: tuple[Path, Path],
) -> None:
    repo = SongRepository.from_files(*song_assets)
    assert {s.title for s in repo.search("dream")} == {"Dream"}
    assert {s.title for s in repo.search("REA")} == {"Dream"}


def test_search_no_match_returns_empty(song_assets: tuple[Path, Path]) -> None:
    repo = SongRepository.from_files(*song_assets)
    assert repo.search("zzzzz") == []
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `uv run pytest tests/game/test_song_repository.py -k search -v`
Expected: FAIL(`ImportError: cannot import name 'SongRepository'`)

- [ ] **Step 3: SongRepository を追加**

`src/game/song_repository.py` の末尾に追記:

```python
class SongRepository:
    """読み込んだ楽曲群への問い合わせを提供する。"""

    def __init__(self, songs: list[Song]) -> None:
        self._songs = songs

    @classmethod
    def from_files(cls, songs_path: Path, images_dir: Path) -> SongRepository:
        return cls(load_songs(songs_path, images_dir))

    @property
    def songs(self) -> list[Song]:
        return list(self._songs)

    def search(self, query: str) -> list[Song]:
        # 入力ゆれを吸収するため正規化+大文字小文字無視で部分一致させる。
        needle = _normalize(query).casefold()
        return [s for s in self._songs if needle in _normalize(s.title).casefold()]
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `uv run pytest tests/game/test_song_repository.py -k search -v`
Expected: PASS(2 件)

- [ ] **Step 5: コミット**

```bash
git add src/game/song_repository.py tests/game/test_song_repository.py
git commit -m "feat: 楽曲の部分一致検索を追加" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: 画像保有曲の抽出(songs_with_image)

隠し曲は画像を持つ曲からのみ抽選するため、画像保有曲を返すメソッドを追加する。

**Files:**
- Modify: `src/game/song_repository.py`(`SongRepository` にメソッド追加)
- Test: `tests/game/test_song_repository.py`(追記)

- [ ] **Step 1: 失敗するテストを追記**

Append to `tests/game/test_song_repository.py`:

```python
def test_songs_with_image(song_assets: tuple[Path, Path]) -> None:
    repo = SongRepository.from_files(*song_assets)
    assert {s.title for s in repo.songs_with_image()} == {"Dream", "Futarimiti"}
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `uv run pytest tests/game/test_song_repository.py -k songs_with_image -v`
Expected: FAIL(`AttributeError: 'SongRepository' object has no attribute 'songs_with_image'`)

- [ ] **Step 3: メソッドを追加**

`SongRepository` に追記:

```python
    def songs_with_image(self) -> list[Song]:
        return [s for s in self._songs if s.image_path is not None]
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `uv run pytest tests/game/test_song_repository.py -k songs_with_image -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add src/game/song_repository.py tests/game/test_song_repository.py
git commit -m "feat: 画像保有曲の抽出を追加" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: 派生一覧(shelves / books / versions)

お題生成の `shelf_list` / `book_list` / `version_list` 解決に使う重複なし一覧を提供する。

**Files:**
- Modify: `src/game/song_repository.py`(`SongRepository` にメソッド追加)
- Test: `tests/game/test_song_repository.py`(追記)

- [ ] **Step 1: 失敗するテストを追記**

Append to `tests/game/test_song_repository.py`:

```python
def test_derived_lists(song_assets: tuple[Path, Path]) -> None:
    repo = SongRepository.from_files(*song_assets)
    assert repo.shelves() == ["II", "Story"]
    assert repo.books() == ["Deemo's collection Vol.1A", "Etude"]
    assert repo.versions() == ["1.0", "2.0", "2.3"]
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `uv run pytest tests/game/test_song_repository.py -k derived_lists -v`
Expected: FAIL(`AttributeError: 'SongRepository' object has no attribute 'shelves'`)

- [ ] **Step 3: メソッドを追加**

`SongRepository` に追記:

```python
    def shelves(self) -> list[str]:
        return sorted({s.shelf for s in self._songs})

    def books(self) -> list[str]:
        return sorted({s.book for s in self._songs})

    def versions(self) -> list[str]:
        return sorted({s.version for s in self._songs})
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `uv run pytest tests/game/test_song_repository.py -k derived_lists -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add src/game/song_repository.py tests/game/test_song_repository.py
git commit -m "feat: 棚/ブック/version の派生一覧を追加" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: 実マスターデータでの結合テスト

合成フィクスチャでは捕えられない実データの構造差(VERSION 表記ゆれ、画像名一致など)を検証する。

**Files:**
- Test: `tests/game/test_song_repository_integration.py`

- [ ] **Step 1: 結合テストを書く**

Create `tests/game/test_song_repository_integration.py`:

```python
from pathlib import Path

from src.game.song_repository import SongRepository

ASSETS = Path(__file__).resolve().parents[2] / "assets"


def test_real_master_data_loads() -> None:
    repo = SongRepository.from_files(
        ASSETS / "data" / "all_songs.json",
        ASSETS / "images",
    )
    titles = {s.title for s in repo.songs}
    assert len(titles) > 100
    assert "Dream" in titles
    assert "Story" in repo.shelves()

    dream = next(s for s in repo.songs if s.title == "Dream")
    assert dream.image_path is not None
    assert dream.image_path.exists()
    assert repo.songs_with_image()  # 画像が解決できる曲が存在する
```

- [ ] **Step 2: テストを実行して成功を確認**

Run: `uv run pytest tests/game/test_song_repository_integration.py -v`
Expected: PASS(失敗する場合は実データのスキーマ差を調査し `_parse_song` を調整)

- [ ] **Step 3: 全テストを実行**

Run: `uv run pytest -v`
Expected: 既存 config テストと本プランの全テストが PASS

- [ ] **Step 4: コミット**

```bash
git add tests/game/test_song_repository_integration.py
git commit -m "test: 実マスターデータでの楽曲読込を検証" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage(song_repository 範囲):**
- 「all_songs.json 読込」→ Task 2 ✓
- 「部分一致検索」→ Task 3 ✓
- 「画像解決」→ Task 2(`_build_image_index` + `_normalize`)+ Task 4 ✓
- 「一覧導出(shelf/book/version)」→ Task 5 ✓
- 「派生属性(ノーツ密度等)」→ 述語を持つ Plan 2 へ意図的に後回し(YAGNI)。本プランの欠落ではない。

**2. Placeholder scan:** プレースホルダなし。全ステップに実コード/実コマンドあり。

**3. Type consistency:** `Difficulty`/`Chart(level, notes)`/`Song`(全フィールド)/`load_songs(songs_path, images_dir) -> list[Song]`/`SongRepository`(`from_files`, `songs`, `search`, `songs_with_image`, `shelves`, `books`, `versions`)が全タスクで一貫。`_normalize` は Task 2 で定義し Task 3 で再利用。

**4. 規約:** 型ヒント必須・`Any` 不使用(JSON 境界は `cast`)・コメントは WHY のみ・docstring はテンプレート様式踏襲・関数は単一責務。
