# 送信メッセージの Embed 化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** bot がユーザーへ送る全メッセージ(ログch転送を除く)を Discord Embed 形式へ統一し、意味ごとに色分けする。

**Architecture:** 共通の Embed ビルダモジュール `src/bot/embeds.py` を新設し、色定数と薄いラッパ関数を提供する。`game_service` と各 cog はこのビルダを呼ぶだけにする。盤面とお題は1つの Embed メッセージへ統合し、`game_service` の状態スロットを単一参照に一本化する。既存の `format_*` 関数は文字列を返したまま据え置き、Embed の description に渡す。

**Tech Stack:** Python 3.12 / discord.py 2.4 / pytest

参照: 設計ドキュメント `docs/superpowers/specs/2026-06-16-embed-messages-design.md`

---

## ファイル構成

- 新規: `src/bot/embeds.py` — 色定数 `EmbedColor` と汎用ビルダ `success/error/warning/info/neutral`
- 新規: `tests/bot/test_embeds.py` — ビルダのユニットテスト
- 変更: `src/bot/game_service.py` — 盤面+お題の統合、状態スロット一本化、アーカイブ/予告の Embed 化
- 変更: `src/cogs/session_start.py`, `session_progress.py`, `answer.py`, `session_end.py`, `session_clear.py`, `song_report.py`, `_base.py`, `_song_input.py` — 各送信を Embed へ
- 変更: `src/bot/client.py` — `_on_app_command_error` の汎用エラー応答を Embed へ(`_consume_log_queue` は据え置き)

テスト実行コマンドは全タスク共通で `uv run pytest`(プロジェクト直下で実行)。

---

### Task 1: Embed ビルダモジュール

**Files:**
- Create: `src/bot/embeds.py`
- Test: `tests/bot/test_embeds.py`

- [ ] **Step 1: Write the failing test**

`tests/bot/test_embeds.py`:

```python
import discord

from src.bot.embeds import EmbedColor, error, info, neutral, success, warning


def test_success_sets_green_color_and_text() -> None:
    """success は緑色で title/description を設定する。"""
    embed = success("完了しました", title="確認")
    assert embed.color == discord.Color(EmbedColor.SUCCESS)
    assert embed.title == "確認"
    assert embed.description == "完了しました"


def test_error_sets_red_color() -> None:
    """error は赤色を設定する。"""
    assert error("失敗").color == discord.Color(EmbedColor.ERROR)


def test_warning_sets_orange_color() -> None:
    """warning はオレンジ色を設定する。"""
    assert warning("注意").color == discord.Color(EmbedColor.WARNING)


def test_info_sets_blue_color() -> None:
    """info は青色を設定する。"""
    assert info("情報").color == discord.Color(EmbedColor.INFO)


def test_neutral_sets_gray_color() -> None:
    """neutral は灰色を設定する。"""
    assert neutral("記録").color == discord.Color(EmbedColor.NEUTRAL)


def test_builder_allows_title_only() -> None:
    """description 省略時は title だけの Embed を作れる(画像用途)。"""
    embed = info(title="盤面とお題")
    assert embed.title == "盤面とお題"
    assert embed.description is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/bot/test_embeds.py -v`
Expected: FAIL(`ModuleNotFoundError: No module named 'src.bot.embeds'`)

- [ ] **Step 3: Write minimal implementation**

`src/bot/embeds.py`:

```python
from __future__ import annotations

from enum import IntEnum

import discord


class EmbedColor(IntEnum):
    """メッセージの意味ごとに割り当てる Embed の色。"""

    SUCCESS = 0x57F287  # 緑: 成功・確認
    ERROR = 0xED4245  # 赤: エラー・不正解
    WARNING = 0xE67E22  # オレンジ: 予告・ガード
    INFO = 0x3498DB  # 青: 情報(盤面・進捗)
    NEUTRAL = 0x95A5A6  # 灰: アーカイブ


def _build(
    color: EmbedColor, description: str | None, title: str | None
) -> discord.Embed:
    """指定色の Embed を組み立てる。

    Args:
        color: 左縁のカラーバーに使う色。
        description: 本文。None なら本文なし。
        title: 見出し。None なら見出しなし。

    Returns:
        discord.Embed: 構築した Embed。
    """
    return discord.Embed(title=title, description=description, color=discord.Color(color))


def success(description: str | None = None, *, title: str | None = None) -> discord.Embed:
    """成功・確認を表す緑色の Embed を返す。

    Args:
        description: 本文。
        title: 見出し。

    Returns:
        discord.Embed: 緑色の Embed。
    """
    return _build(EmbedColor.SUCCESS, description, title)


def error(description: str | None = None, *, title: str | None = None) -> discord.Embed:
    """エラー・不正解を表す赤色の Embed を返す。

    Args:
        description: 本文。
        title: 見出し。

    Returns:
        discord.Embed: 赤色の Embed。
    """
    return _build(EmbedColor.ERROR, description, title)


def warning(description: str | None = None, *, title: str | None = None) -> discord.Embed:
    """予告・ガードを表すオレンジ色の Embed を返す。

    Args:
        description: 本文。
        title: 見出し。

    Returns:
        discord.Embed: オレンジ色の Embed。
    """
    return _build(EmbedColor.WARNING, description, title)


def info(description: str | None = None, *, title: str | None = None) -> discord.Embed:
    """情報を表す青色の Embed を返す。

    Args:
        description: 本文。
        title: 見出し。

    Returns:
        discord.Embed: 青色の Embed。
    """
    return _build(EmbedColor.INFO, description, title)


def neutral(description: str | None = None, *, title: str | None = None) -> discord.Embed:
    """アーカイブを表す灰色の Embed を返す。

    Args:
        description: 本文。
        title: 見出し。

    Returns:
        discord.Embed: 灰色の Embed。
    """
    return _build(EmbedColor.NEUTRAL, description, title)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/bot/test_embeds.py -v`
Expected: PASS(7 件)

- [ ] **Step 5: Commit**

```bash
git add src/bot/embeds.py tests/bot/test_embeds.py
git commit -m "feat: Embed 共通ビルダ embeds モジュールを追加"
```

---

### Task 2: game_service の盤面+お題統合とアーカイブ/予告 Embed 化

**Files:**
- Modify: `src/bot/game_service.py`

このタスクは Discord 送信が絡むため自動テストは追加せず、既存テストの非破壊を回帰確認とする。

- [ ] **Step 1: import を追加**

`src/bot/game_service.py` 冒頭の import 群へ追加する(`import discord` の直後):

```python
from src.bot import embeds
```

- [ ] **Step 2: 盤面メッセージ用の定数とタイトルを定義**

`BOARD_FILENAME = "board.png"` の直後に追加:

```python
SESSION_EMBED_TITLE = "盤面とお題"
ARCHIVE_EMBED_TITLE = "セッション終了"
WARNING_EMBED_TITLE = "終了予告"
```

- [ ] **Step 3: 状態スロットを単一参照へ一本化**

`__init__` の以下2行:

```python
        self.board_message: discord.Message | None = None
        self.topic_message: discord.Message | None = None
```

を次の1行へ置き換える:

```python
        # 盤面画像とお題リストを1つの Embed メッセージにまとめて保持する。
        self.session_message: discord.Message | None = None
```

- [ ] **Step 4: 盤面+お題 Embed を組み立てるヘルパを追加**

`render_current_board` メソッドの直後にプライベートメソッドを追加:

```python
    def _build_session_embed(self) -> discord.Embed:
        """盤面画像とお題リストを1つにまとめた Embed を組み立てる。

        Returns:
            discord.Embed: お題リストを本文に持ち、盤面画像を添付参照する青色 Embed。

        Raises:
            NoActiveSessionError: アクティブなセッションが無い場合。
        """
        session = self.session_manager.require_active()
        embed = embeds.info(
            format_topic_list(session.topics), title=SESSION_EMBED_TITLE
        )
        embed.set_image(url=f"attachment://{BOARD_FILENAME}")
        return embed
```

- [ ] **Step 5: post_session_messages を1メッセージ統合へ書き換え**

既存の `post_session_messages` 本体を次へ置き換える:

```python
    async def post_session_messages(self, channel: discord.abc.Messageable) -> None:
        """盤面とお題リストを1つの Embed として投稿しピン留めし、参照を保持する。

        Args:
            channel: 投稿先チャンネル。
        """
        png = self.render_current_board()
        message = await channel.send(
            embed=self._build_session_embed(),
            file=discord.File(BytesIO(png), filename=BOARD_FILENAME),
        )
        await message.pin()
        self.session_message = message
```

- [ ] **Step 6: refresh_board を単一メッセージ編集へ書き換え**

既存の `refresh_board` 本体を次へ置き換える:

```python
    async def refresh_board(self) -> None:
        """盤面画像とお題リストの Embed メッセージを現在の状態へ更新する。"""
        if self.session_message is None:
            return
        png = self.render_current_board()
        await self.session_message.edit(
            embed=self._build_session_embed(),
            attachments=[discord.File(BytesIO(png), filename=BOARD_FILENAME)],
        )
```

- [ ] **Step 7: end_session のアーカイブ投稿を灰色 Embed へ**

`end_session` 内の以下のブロック:

```python
        await archive_channel.send(
            content=format_archive_caption(session),
            file=discord.File(BytesIO(png), filename=BOARD_FILENAME),
        )
```

を次へ置き換える:

```python
        archive_embed = embeds.neutral(
            format_archive_caption(session), title=ARCHIVE_EMBED_TITLE
        )
        archive_embed.set_image(url=f"attachment://{BOARD_FILENAME}")
        await archive_channel.send(
            embed=archive_embed,
            file=discord.File(BytesIO(png), filename=BOARD_FILENAME),
        )
```

- [ ] **Step 8: _unpin_messages を単一参照へ書き換え**

既存の `_unpin_messages` 本体を次へ置き換える:

```python
    async def _unpin_messages(self) -> None:
        """盤面+お題メッセージのピンを解除し、参照を落とす。"""
        if self.session_message is not None:
            await self.session_message.unpin()
        self.session_message = None
```

- [ ] **Step 9: run_timer の予告送信を Embed 化し参照名を更新**

`run_timer` 内の以下のブロック:

```python
        if self.board_message is not None:
            await self.board_message.channel.send(
                f"残り{self._settings.session_warning_minutes}分です。"
            )
```

を次へ置き換える:

```python
        if self.session_message is not None:
            await self.session_message.channel.send(
                embed=embeds.warning(
                    f"残り{self._settings.session_warning_minutes}分です。",
                    title=WARNING_EMBED_TITLE,
                )
            )
```

- [ ] **Step 10: 既存テストで回帰確認**

Run: `uv run pytest tests/bot/test_game_service.py tests/bot/test_game_service_integration.py -v`
Expected: PASS(全件。`format_*` / `timer_delays` 等は無変更のため通る)

- [ ] **Step 11: Commit**

```bash
git add src/bot/game_service.py
git commit -m "feat: 盤面+お題を1つの Embed に統合しアーカイブ/予告を Embed 化"
```

---

### Task 3: progress / report cog の Embed 化(画像付き・公開達成)

**Files:**
- Modify: `src/cogs/session_progress.py`
- Modify: `src/cogs/song_report.py`

- [ ] **Step 1: session_progress.py の import を更新**

`src/cogs/session_progress.py` の import 群へ追加:

```python
from src.bot import embeds
```

- [ ] **Step 2: progress の応答を青色 Embed(画像付き)へ**

`progress` メソッド内の以下のブロック:

```python
        await interaction.followup.send(
            content=format_progress_text(session, remaining),
            file=discord.File(BytesIO(png), filename=BOARD_FILENAME),
            ephemeral=True,
        )
```

を次へ置き換える:

```python
        embed = embeds.info(format_progress_text(session, remaining))
        embed.set_image(url=f"attachment://{BOARD_FILENAME}")
        await interaction.followup.send(
            embed=embed,
            file=discord.File(BytesIO(png), filename=BOARD_FILENAME),
            ephemeral=True,
        )
```

- [ ] **Step 3: song_report.py の import を更新**

`src/cogs/song_report.py` の import 群へ追加:

```python
from src.bot import embeds
```

- [ ] **Step 4: report の各応答を Embed へ**

`report` メソッド内、`if newly_completed:` ブロック以降を次へ置き換える:

```python
        if newly_completed:
            channel = await self._require_command_channel_or_reply(interaction)
            if channel is None:
                return
            await channel.send(
                embed=embeds.success(
                    format_completed_topics(newly_completed), title="お題達成"
                )
            )
            await interaction.followup.send(
                embed=embeds.success("申告を反映しました。"), ephemeral=True
            )
        else:
            await interaction.followup.send(
                embed=embeds.info("申告を反映しました。達成したお題はありません。"),
                ephemeral=True,
            )
```

なお既存の `discord.Embed` 直接生成は上記で置き換わるため、`discord` import が他で未使用なら残してよい(`interaction: discord.Interaction` で使用しているため削除不要)。

- [ ] **Step 5: 回帰確認(import 健全性)**

Run: `uv run pytest -v`
Expected: PASS(全件。cog は送信が外部依存のため新規テストなし、既存が緑であること)

- [ ] **Step 6: Commit**

```bash
git add src/cogs/session_progress.py src/cogs/song_report.py
git commit -m "feat: progress/report の応答を Embed 化"
```

---

### Task 4: 確認・ガード系 cog の Embed 化

**Files:**
- Modify: `src/cogs/session_start.py`
- Modify: `src/cogs/answer.py`
- Modify: `src/cogs/session_end.py`
- Modify: `src/cogs/session_clear.py`

- [ ] **Step 1: session_start.py の import を更新**

`src/cogs/session_start.py` の import 群へ追加:

```python
from src.bot import embeds
```

- [ ] **Step 2: session_start の2応答を Embed へ**

「既にセッションが進行中です。」(ガード)はオレンジ、「セッションを開始しました。」は緑。

以下:

```python
            await interaction.response.send_message(
                "既にセッションが進行中です。", ephemeral=True
            )
```

を:

```python
            await interaction.response.send_message(
                embed=embeds.warning("既にセッションが進行中です。"), ephemeral=True
            )
```

以下:

```python
        await interaction.followup.send("セッションを開始しました。", ephemeral=True)
```

を:

```python
        await interaction.followup.send(
            embed=embeds.success("セッションを開始しました。"), ephemeral=True
        )
```

- [ ] **Step 3: answer.py の import を更新**

`src/cogs/answer.py` の import 群へ追加:

```python
from src.bot import embeds
```

- [ ] **Step 4: answer の正解/不正解を緑/赤 Embed へ**

以下:

```python
        await interaction.response.send_message(
            "正解" if correct else "不正解", ephemeral=True
        )
```

を:

```python
        embed = embeds.success("正解") if correct else embeds.error("不正解")
        await interaction.response.send_message(embed=embed, ephemeral=True)
```

- [ ] **Step 5: session_end.py の import を更新**

`src/cogs/session_end.py` の import 群へ追加:

```python
from src.bot import embeds
```

- [ ] **Step 6: session_end の完了応答を緑 Embed へ**

以下:

```python
        await interaction.followup.send("セッションを終了しました。", ephemeral=True)
```

を:

```python
        await interaction.followup.send(
            embed=embeds.success("セッションを終了しました。"), ephemeral=True
        )
```

- [ ] **Step 7: session_clear.py の import を更新**

`src/cogs/session_clear.py` の import 群へ追加:

```python
from src.bot import embeds
```

- [ ] **Step 8: session_clear の破棄応答を緑 Embed へ**

以下:

```python
        await interaction.response.send_message(
            "セッションを破棄しました。", ephemeral=True
        )
```

を:

```python
        await interaction.response.send_message(
            embed=embeds.success("セッションを破棄しました。"), ephemeral=True
        )
```

- [ ] **Step 9: 回帰確認**

Run: `uv run pytest -v`
Expected: PASS(全件)

- [ ] **Step 10: Commit**

```bash
git add src/cogs/session_start.py src/cogs/answer.py src/cogs/session_end.py src/cogs/session_clear.py
git commit -m "feat: 確認・ガード系 cog の応答を Embed 化"
```

---

### Task 5: 共通ヘルパ・解決失敗・汎用エラーの Embed 化

**Files:**
- Modify: `src/cogs/_base.py`
- Modify: `src/cogs/_song_input.py`
- Modify: `src/bot/client.py`

- [ ] **Step 1: _base.py の import を更新**

`src/cogs/_base.py` の import 群へ追加:

```python
from src.bot import embeds
```

- [ ] **Step 2: _base.py の3つのエラー応答を赤 Embed へ**

`_require_session_or_reply` 内:

```python
            await interaction.response.send_message(
                "進行中のセッションがありません。", ephemeral=True
            )
```

を:

```python
            await interaction.response.send_message(
                embed=embeds.error("進行中のセッションがありません。"), ephemeral=True
            )
```

`_require_command_channel_or_reply` 内:

```python
        await interaction.followup.send(
            "このチャンネルには投稿できません。", ephemeral=True
        )
```

を:

```python
        await interaction.followup.send(
            embed=embeds.error("このチャンネルには投稿できません。"), ephemeral=True
        )
```

`_require_archive_channel_or_reply` 内:

```python
        await interaction.followup.send(
            "アーカイブ用チャンネルを取得できませんでした。設定を確認してください。",
            ephemeral=True,
        )
```

を:

```python
        await interaction.followup.send(
            embed=embeds.error(
                "アーカイブ用チャンネルを取得できませんでした。設定を確認してください。"
            ),
            ephemeral=True,
        )
```

- [ ] **Step 3: _song_input.py の import を更新**

`src/cogs/_song_input.py` の import 群へ追加:

```python
from src.bot import embeds
```

- [ ] **Step 4: 解決失敗の2応答を Embed へ(未発見=赤・複数候補=オレンジ)**

`_resolve_or_reply` 内:

```python
        except SongNotFound:
            await interaction.response.send_message(
                f"「{song}」に一致する曲が見つかりません。", ephemeral=True
            )
        except AmbiguousSong as exc:
            names = "、".join(s.title for s in exc.matches[:10])
            await interaction.response.send_message(
                f"候補が複数あります。曲名を絞ってください: {names}", ephemeral=True
            )
```

を:

```python
        except SongNotFound:
            await interaction.response.send_message(
                embed=embeds.error(f"「{song}」に一致する曲が見つかりません。"),
                ephemeral=True,
            )
        except AmbiguousSong as exc:
            names = "、".join(s.title for s in exc.matches[:10])
            await interaction.response.send_message(
                embed=embeds.warning(
                    f"候補が複数あります。曲名を絞ってください: {names}"
                ),
                ephemeral=True,
            )
```

- [ ] **Step 5: client.py の汎用エラー応答を赤 Embed へ**

`src/bot/client.py` の import 群へ追加:

```python
from src.bot import embeds
```

`_on_app_command_error` 内:

```python
        if interaction.response.is_done():
            await interaction.followup.send(GENERIC_ERROR_MESSAGE, ephemeral=True)
        else:
            await interaction.response.send_message(GENERIC_ERROR_MESSAGE, ephemeral=True)
```

を:

```python
        if interaction.response.is_done():
            await interaction.followup.send(
                embed=embeds.error(GENERIC_ERROR_MESSAGE), ephemeral=True
            )
        else:
            await interaction.response.send_message(
                embed=embeds.error(GENERIC_ERROR_MESSAGE), ephemeral=True
            )
```

`_consume_log_queue` のコードブロック転送は据え置き(変更しない)。

- [ ] **Step 6: 回帰確認**

Run: `uv run pytest -v`
Expected: PASS(全件)

- [ ] **Step 7: Commit**

```bash
git add src/cogs/_base.py src/cogs/_song_input.py src/bot/client.py
git commit -m "feat: 共通ヘルパ・解決失敗・汎用エラー応答を Embed 化"
```

---

## 完了基準

- `uv run pytest -v` が全件 PASS。
- ログチャンネル転送を除く全送信箇所が Embed を使用している(`content=` 文字列の直接送信が残っていないこと。`Grep` で `send_message\(\s*"` / `\.send\(\s*"` / `content=` を確認)。
- 盤面とお題が1メッセージに統合され、`board_message` / `topic_message` の参照が残っていない。
