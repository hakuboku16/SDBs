# 楽曲名オートコンプリート実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/report`・`/answer` の `song` 引数に Discord オートコンプリート(入力中の曲名候補表示)を追加し、候補選択後の送信が確実に解決されるよう `resolve_song` を完全一致優先に小改修する。

**Architecture:** Discord 非依存の候補抽出を `GameService.suggest_song_titles` として、完全一致優先解決を `GameService.resolve_song` 改修として TDD する。既存 `SongRepository.search`(NFC 正規化 + 大文字小文字無視の部分一致)を再利用する。cog は autocomplete コールバックを `GameService` へ委譲する薄いアダプタとし、import スモークで検証する。

**Tech Stack:** Python 3.12 / uv / pytest / discord.py 2.4

**前提:** M5-T3(`/report`・`/answer`・`/progress` cog)が完了していること。設計書 [2026-06-13-song-autocomplete-design.md](../specs/2026-06-13-song-autocomplete-design.md)。

---

## 現状(着手前の事実)

- [src/bot/game_service.py](src/bot/game_service.py) の `GameService`:
  - `resolve_song(query)->Song`(部分一致。0件→`SongNotFound` / 複数→`AmbiguousSong` / 1件→その曲)。内部で `self._repo.search(query)` を使用。
  - 属性 `_repo: SongRepository`。
- [src/game/song_repository.py](src/game/song_repository.py):
  - `search(query)->list[Song]`(NFC 正規化 + casefold の部分一致)。
  - `songs` プロパティ(全曲のコピー)。`_normalize(text)` モジュール関数。
- [src/cogs/song_report.py](src/cogs/song_report.py) / [src/cogs/answer.py](src/cogs/answer.py):`song: str` 引数を持つ app command。autocomplete 未配線。
- [tests/bot/test_game_service.py](tests/bot/test_game_service.py):ヘルパ `_song(title, *, image=False)->Song` と `_service(songs)->GameService` が定義済み。

## ファイル構成

- 変更: `src/bot/game_service.py`(`suggest_song_titles` 追加、`resolve_song` 完全一致優先化)
- 変更: `tests/bot/test_game_service.py`(上記 2 つの単体テストを追加)
- 変更: `src/cogs/song_report.py`(`song` の autocomplete コールバック配線)
- 変更: `src/cogs/answer.py`(`song` の autocomplete コールバック配線)

---

## Task 1: resolve_song を完全一致優先にする

**Files:**
- Modify: `src/bot/game_service.py`
- Test: `tests/bot/test_game_service.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/bot/test_game_service.py` の `test_resolve_song_multiple_matches_raises_ambiguous`(複数一致テスト)の直後に追記する。

```python
def test_resolve_song_exact_title_match_wins_over_substring() -> None:
    """query が曲名と完全一致するなら、部分文字列で複数ヒットしてもその曲を返す。"""
    service = _service([_song("Dream"), _song("Dreamy")])
    assert service.resolve_song("Dream").title == "Dream"


def test_resolve_song_exact_match_is_normalized_and_case_insensitive() -> None:
    """完全一致判定は正規化 + 大文字小文字無視で行う。"""
    service = _service([_song("Dream"), _song("Dreamy")])
    assert service.resolve_song("dream").title == "Dream"
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `APP_ENV=test uv run pytest tests/bot/test_game_service.py -k "exact" -v`
Expected: FAIL(`AmbiguousSong` が送出され、`resolve_song("Dream")` がアサーションに到達しない)

- [ ] **Step 3: resolve_song を改修**

`src/bot/game_service.py` の import 行 `from src.game.song_repository import SongRepository` を次へ置き換える。

```python
from src.game.song_repository import SongRepository, _normalize
```

`resolve_song` 本体を次へ置き換える。

```python
    def resolve_song(self, query: str) -> Song:
        """部分一致で曲を 1 件に解決する。完全一致する曲名があれば優先する。

        Args:
            query: 検索語。

        Returns:
            Song: 一意に解決した曲。

        Raises:
            SongNotFound: 部分一致が 0 件の場合。
            AmbiguousSong: 完全一致が無く部分一致が複数件の場合。
        """
        matches = self._repo.search(query)
        if not matches:
            raise SongNotFound(query)
        # オートコンプリートで選んだ曲名が別曲名の部分文字列でも確実に解決できるよう、
        # 正規化後に完全一致する曲があればそれを優先する。
        needle = _normalize(query).casefold()
        for song in matches:
            if _normalize(song.title).casefold() == needle:
                return song
        if len(matches) > 1:
            raise AmbiguousSong(matches)
        return matches[0]
```

- [ ] **Step 4: テストが通ることを確認**

Run: `APP_ENV=test uv run pytest tests/bot/test_game_service.py -k "resolve_song" -v`
Expected: PASS(既存 3 件 + 新規 2 件すべて通過)

- [ ] **Step 5: コミット**

```bash
git add src/bot/game_service.py tests/bot/test_game_service.py
git commit -m "feat: resolve_song を完全一致優先に改修(候補選択の確実な解決)"
```

---

## Task 2: suggest_song_titles を追加

**Files:**
- Modify: `src/bot/game_service.py`
- Test: `tests/bot/test_game_service.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/bot/test_game_service.py` の末尾へ追記する。`_song` / `_service` ヘルパは定義済みのものを再利用する。

```python
def test_suggest_song_titles_empty_query_returns_first_n_sorted() -> None:
    """空入力なら全曲名を昇順ソートし先頭 limit 件を返す。"""
    service = _service([_song("Cytus"), _song("Anima"), _song("Bond")])
    assert service.suggest_song_titles("", limit=2) == ["Anima", "Bond"]


def test_suggest_song_titles_filters_by_partial_match_sorted() -> None:
    """非空入力は部分一致で絞り込み、曲名昇順で返す。"""
    service = _service([_song("Dreamy"), _song("Dream"), _song("Pulses")])
    assert service.suggest_song_titles("dre") == ["Dream", "Dreamy"]


def test_suggest_song_titles_caps_at_limit() -> None:
    """一致が limit を超えても limit 件で打ち切る。"""
    service = _service([_song(f"Song{i:02d}") for i in range(30)])
    assert len(service.suggest_song_titles("Song", limit=25)) == 25
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `APP_ENV=test uv run pytest tests/bot/test_game_service.py -k "suggest" -v`
Expected: FAIL(`AttributeError: 'GameService' object has no attribute 'suggest_song_titles'`)

- [ ] **Step 3: suggest_song_titles を実装**

`src/bot/game_service.py` の `resolve_song` メソッドの直後へ追加する。

```python
    def suggest_song_titles(self, query: str, *, limit: int = 25) -> list[str]:
        """オートコンプリート用に曲名候補を返す。

        Args:
            query: 入力中の検索語。空なら全曲が対象。
            limit: 返す最大件数。Discord の候補上限に合わせ既定 25。

        Returns:
            list[str]: 曲名昇順で先頭 limit 件の曲名。
        """
        songs = self._repo.songs if not query.strip() else self._repo.search(query)
        titles = sorted(song.title for song in songs)
        return titles[:limit]
```

- [ ] **Step 4: テストが通ることを確認**

Run: `APP_ENV=test uv run pytest tests/bot/test_game_service.py -v`
Expected: PASS(本タスクの 3 件を含め全件通過)

- [ ] **Step 5: コミット**

```bash
git add src/bot/game_service.py tests/bot/test_game_service.py
git commit -m "feat: 曲名オートコンプリート候補抽出 suggest_song_titles を追加"
```

---

## Task 3: /report cog に autocomplete を配線

**Files:**
- Modify: `src/cogs/song_report.py`

- [ ] **Step 1: autocomplete コールバックを追加して配線する**

`SongReportCog` クラス内、`__init__` の直後(`report` メソッドより前)へコールバックを追加し、`report` のデコレータ群へ autocomplete を加える。最終的な該当部分は次の並びになる。

```python
    def __init__(self, bot: GameBot) -> None:
        """bot を保持して初期化する。

        Args:
            bot: コマンドを提供する GameBot。
        """
        self.bot = bot

    async def _song_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """曲名候補を返す。セッション有無に関わらず全曲を対象にする。

        Args:
            interaction: オートコンプリートのインタラクション。
            current: 入力中の文字列。

        Returns:
            list[app_commands.Choice[str]]: 曲名候補(最大 25 件)。
        """
        return [
            app_commands.Choice(name=title, value=title)
            for title in self.bot.game.suggest_song_titles(current)
        ]

    @app_commands.command(name="report", description="プレイ結果を申告する")
    @app_commands.describe(
        song="曲名(部分一致)",
        difficulty="難易度",
        combo="獲得コンボ数",
        charming="獲得チャーミング数",
    )
    @app_commands.choices(difficulty=_DIFFICULTY_CHOICES)
    @app_commands.autocomplete(song=_song_autocomplete)
    async def report(
```

- [ ] **Step 2: import スモークで検証**

Run: `uv run python -c "import src.cogs.song_report; print('ok')"`
Expected: `ok`

- [ ] **Step 3: コミット**

```bash
git add src/cogs/song_report.py
git commit -m "feat: /report の song にオートコンプリートを配線"
```

---

## Task 4: /answer cog に autocomplete を配線

**Files:**
- Modify: `src/cogs/answer.py`

- [ ] **Step 1: autocomplete コールバックを追加して配線する**

`AnswerCog` クラス内、`__init__` の直後(`answer` メソッドより前)へコールバックを追加し、`answer` のデコレータ群へ autocomplete を加える。最終的な該当部分は次の並びになる。

```python
    def __init__(self, bot: GameBot) -> None:
        """bot を保持して初期化する。

        Args:
            bot: コマンドを提供する GameBot。
        """
        self.bot = bot

    async def _song_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """曲名候補を返す。セッション有無に関わらず全曲を対象にする。

        Args:
            interaction: オートコンプリートのインタラクション。
            current: 入力中の文字列。

        Returns:
            list[app_commands.Choice[str]]: 曲名候補(最大 25 件)。
        """
        return [
            app_commands.Choice(name=title, value=title)
            for title in self.bot.game.suggest_song_titles(current)
        ]

    @app_commands.command(name="answer", description="隠し曲を当てる")
    @app_commands.describe(song="曲名(部分一致)")
    @app_commands.autocomplete(song=_song_autocomplete)
    async def answer(self, interaction: discord.Interaction, song: str) -> None:
```

- [ ] **Step 2: import スモークで検証**

Run: `uv run python -c "import src.cogs.answer; print('ok')"`
Expected: `ok`

- [ ] **Step 3: 全 cog ロードのスモーク + 全自動テスト回帰**

Run: `uv run python -c "import src.cogs.session_start, src.cogs.session_end, src.cogs.session_clear, src.cogs.song_report, src.cogs.answer, src.cogs.session_progress; print('ok')"`
Expected: `ok`(6 cog すべてが import できる)

Run: `APP_ENV=test uv run pytest -q`
Expected: PASS(既存 + 本計画のテストが全件通過)

- [ ] **Step 4: コミット**

```bash
git add src/cogs/answer.py
git commit -m "feat: /answer の song にオートコンプリートを配線"
```

---

## 手動結合テスト(実機・自動化対象外)

ピン留め権限付与後、`.env` 設定済みの状態で `uv run python -m src.main` で確認する。

1. `/report song:` … 未入力で先頭 25 件の曲名候補が出る。
2. `/report song:dr` … 部分一致(大文字小文字無視)で曲名候補が絞り込まれる。
3. 候補から曲名を選んで申告 … 「候補が複数」にならず確実に解決される(部分文字列が重複する曲でも)。
4. `/answer song:` … 同様に候補が出る。

---

## Self-Review(立案者チェック結果)

- **スペック対応**: suggest_song_titles(空→先頭N件・部分一致・25件上限)→ Task 2。resolve_song 完全一致優先 → Task 1。/report・/answer の autocomplete 配線 → Task 3/4。非対象(メタ情報・ファジー・ページング)は実装しない。
- **プレースホルダ無し**: 各ステップに実コード・実コマンド・期待結果を記載。
- **型整合**: `suggest_song_titles(query, *, limit=25)->list[str]` を Task 2 で定義し Task 3/4 のコールバックで使用。`resolve_song` の戻り型・例外は既存維持。autocomplete コールバックは `list[app_commands.Choice[str]]` を返し discord.py の規約に一致。`_normalize` は song_repository の既存モジュール関数を再利用。
- **テスト切り分け**: Discord 非依存の suggest_song_titles・resolve_song のみ TDD。cog は import スモーク + 手動結合テストで検証。
