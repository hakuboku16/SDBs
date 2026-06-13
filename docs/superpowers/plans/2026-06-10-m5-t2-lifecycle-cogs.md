# M5-T2 ライフサイクル系 cog 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** セッションのライフサイクルを司る 3 つの cog(`/session_start`・`/session_end`・`/session_clear`)を実装し、盤面/お題リストの投稿・ピン留め・編集、30 分タイマー、アーカイブ投稿までを `GameService` 経由で配線する。

**Architecture:** Discord I/O(メッセージ投稿・ピン・編集・アーカイブ・タイマータスク実走行)は `GameService` の非同期メソッドへ集約し、cog はコマンド引数の受け取りと `GameService` 呼び出しに徹する薄いアダプタとする。Discord に依存しない純粋ロジック(アーカイブ文言整形)は TDD し、Discord I/O と cog 配線は import スモーク + 手動結合テストで検証する(T1・M1 と同方針)。

**Tech Stack:** Python 3.12 / uv / pytest / discord.py 2.4 / Pillow

**前提:** M5-T1(`GameService` 足場)が完了していること。本計画は T1 で作った `GameService` を拡張する。

---

## 現状(着手前の事実・T1 完了時点)

- [src/bot/game_service.py](src/bot/game_service.py) に `GameService`:
  - 同期メソッド `resolve_song(query)->Song` / `start_session(*, panel_count, rotate, grayscale, mosaic_px, now)->GameSession` / `render_current_board()->bytes` / `cancel_timer()`。
  - プロパティ `session->GameSession | None`、属性 `session_manager: SessionManager` / `board_message` / `topic_message` / `timer_task`(いずれも `object | None`)/ `_settings` / `_rng`。
  - モジュール関数 `format_topic_list(topics)->str` / `timer_delays(session, *, now, warning_minutes)->tuple[float,float]`。
  - 例外 `SongNotFound` / `AmbiguousSong`、定数 `GENERIC_ERROR_MESSAGE`。
- [src/bot/client.py](src/bot/client.py) の `GameBot` は `self.game: GameService` を保持し、`_load_cogs` で `src/cogs/*.py` を `load_extension` する。各 cog は `async def setup(bot)` を要求する。
- [src/game/session_manager.py](src/game/session_manager.py) … `apply_report` は内部で `revealed_panels` を更新する。`end()->GameSession` / `clear()->None`。
- [src/core/config.py](src/core/config.py) … `session_duration_minutes` / `session_warning_minutes` / `archive_channel_id`。

## ファイル構成

- 変更: `src/bot/game_service.py`(Discord I/O 非同期メソッド・アーカイブ文言整形・属性の型付け・`settings` プロパティを追加)
- 変更: `tests/bot/test_game_service.py`(`format_archive_caption` の単体テストを追加)
- 作成: `src/cogs/session_start.py`(`/session_start`)
- 作成: `src/cogs/session_end.py`(`/session_end`)
- 作成: `src/cogs/session_clear.py`(`/session_clear`)

## 盤面ファイル名

盤面 PNG の添付名は全コマンドで `board.png` に統一する(`GameService` 内の定数 `BOARD_FILENAME`)。

---

## Task 1: GameService に Discord I/O とアーカイブ文言を追加

**Files:**
- Modify: `src/bot/game_service.py`
- Test: `tests/bot/test_game_service.py`

- [ ] **Step 1: 失敗するテストを書く(アーカイブ文言)**

`tests/bot/test_game_service.py` の末尾へ追記する。

```python
from datetime import datetime, timedelta

from src.bot.game_service import format_archive_caption
from src.game.models import GameSession, ImageOptions


def _session_with_answerers(answerers: set[int]) -> GameSession:
    """正解者集合だけ意味を持つ最小セッションを作る。

    Args:
        answerers: correct_answerers に入れるユーザー ID 集合。

    Returns:
        GameSession: 構築したセッション。
    """
    now = datetime(2026, 6, 10, 12, 0, 0)
    return GameSession(
        panel_count=4,
        hidden_song=_song("Dream", image=True),
        image_options=ImageOptions(rotate=None, grayscale=False, mosaic_px=None),
        topics=[],
        started_at=now,
        ends_at=now + timedelta(minutes=30),
        correct_answerers=answerers,
    )


def test_archive_caption_spoiler_tags_title_and_lists_answerers() -> None:
    """曲名はネタバレ記法で隠し、正解者はメンション列挙する。"""
    caption = format_archive_caption(_session_with_answerers({111, 222}))
    assert caption == "隠し曲: ||Dream||\n正解者: <@111>、<@222>"


def test_archive_caption_shows_none_when_no_answerers() -> None:
    """正解者がいなければ「なし」と表示する。"""
    caption = format_archive_caption(_session_with_answerers(set()))
    assert caption == "隠し曲: ||Dream||\n正解者: なし"
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `APP_ENV=test uv run pytest tests/bot/test_game_service.py -k archive -v`
Expected: FAIL(`ImportError: cannot import name 'format_archive_caption'`)

- [ ] **Step 3: import・定数・属性型・settings プロパティを追加**

`src/bot/game_service.py` の import 群へ次を追加する。

```python
import asyncio
from io import BytesIO

import discord
```

モジュール先頭付近(`GENERIC_ERROR_MESSAGE` の近く)へ定数を追加する。

```python
BOARD_FILENAME = "board.png"
```

`GameService.__init__` の Discord 側状態スロットを、discord 型で注釈し直す(T1 の `object | None` 3 行を置き換える)。

```python
        # Discord 側状態。投稿・タイマー開始時に実体を入れる。
        self.board_message: discord.Message | None = None
        self.topic_message: discord.Message | None = None
        self.timer_task: asyncio.Task[None] | None = None
```

`cancel_timer` の型注釈と整合させるため、`GameService` へ `settings` プロパティを追加する(`session` プロパティの隣に置く)。

```python
    @property
    def settings(self) -> BaseAppSettings:
        """保持するアプリ設定を返す。

        Returns:
            BaseAppSettings: チャンネル ID・セッション時間等の設定。
        """
        return self._settings
```

- [ ] **Step 4: アーカイブ文言整形を実装**

`src/bot/game_service.py` の `format_topic_list` 関数の直後へモジュール関数を追加する。

```python
def format_archive_caption(session: GameSession) -> str:
    """セッション終了アーカイブ用の文言を生成する。

    Args:
        session: 終了するセッション。

    Returns:
        str: 隠し曲名をネタバレ記法で隠し、正解者をメンション列挙した文言。
    """
    answerers = sorted(session.correct_answerers)
    mentions = "、".join(f"<@{uid}>" for uid in answerers) if answerers else "なし"
    return f"隠し曲: ||{session.hidden_song.title}||\n正解者: {mentions}"
```

- [ ] **Step 5: Discord I/O 非同期メソッドを実装**

`GameService` クラスの末尾へ次のメソッド群を追加する。

```python
    async def post_session_messages(self, channel: discord.abc.Messageable) -> None:
        """盤面とお題リストを投稿してピン留めし、参照を保持する。

        Args:
            channel: 投稿先チャンネル。
        """
        session = self.session_manager._require_active()
        png = self.render_current_board()
        board_msg = await channel.send(
            file=discord.File(BytesIO(png), filename=BOARD_FILENAME)
        )
        topic_msg = await channel.send(format_topic_list(session.topics))
        await board_msg.pin()
        await topic_msg.pin()
        self.board_message = board_msg
        self.topic_message = topic_msg

    async def refresh_board(self) -> None:
        """盤面とお題リストのメッセージを現在の状態へ更新する。"""
        session = self.session_manager._require_active()
        png = self.render_current_board()
        if self.board_message is not None:
            await self.board_message.edit(
                attachments=[discord.File(BytesIO(png), filename=BOARD_FILENAME)]
            )
        if self.topic_message is not None:
            await self.topic_message.edit(content=format_topic_list(session.topics))

    async def end_session(self, archive_channel: discord.abc.Messageable) -> GameSession:
        """現時点の盤面をアーカイブし、ピンを解除してセッションを終了する。

        Args:
            archive_channel: アーカイブ投稿先チャンネル。

        Returns:
            GameSession: 終了直前の最終セッション。

        Raises:
            NoActiveSessionError: アクティブなセッションが無い場合。
        """
        session = self.session_manager._require_active()
        png = self.render_current_board()
        await archive_channel.send(
            content=format_archive_caption(session),
            file=discord.File(BytesIO(png), filename=BOARD_FILENAME),
        )
        await self._unpin_messages()
        # 自動終了経由ではタイマー自身がこの後終了するため、ここでは取り消さず参照だけ落とす。
        self.timer_task = None
        return self.session_manager.end()

    async def clear_session(self) -> None:
        """アーカイブせずにセッションを強制破棄する。

        Raises:
            NoActiveSessionError: アクティブなセッションが無い場合。
        """
        self.cancel_timer()
        await self._unpin_messages()
        self.session_manager.clear()

    async def _unpin_messages(self) -> None:
        """盤面・お題リストのピンを解除し、参照を落とす。"""
        for message in (self.board_message, self.topic_message):
            if message is not None:
                await message.unpin()
        self.board_message = None
        self.topic_message = None

    async def run_timer(
        self, archive_channel: discord.abc.Messageable, *, now: datetime
    ) -> None:
        """予告と自動終了を行うタイマーを実走する。

        Args:
            archive_channel: 自動終了時のアーカイブ投稿先。
            now: 開始時刻。残り時間計算の基準。
        """
        session = self.session_manager._require_active()
        warning_seconds, end_seconds = timer_delays(
            session, now=now, warning_minutes=self._settings.session_warning_minutes
        )
        if warning_seconds > 0:
            await asyncio.sleep(warning_seconds)
        if self.board_message is not None:
            await self.board_message.channel.send(
                f"残り{self._settings.session_warning_minutes}分です。"
            )
        await asyncio.sleep(max(end_seconds - max(warning_seconds, 0.0), 0.0))
        await self.end_session(archive_channel)
```

- [ ] **Step 6: テストが通ることを確認**

Run: `APP_ENV=test uv run pytest tests/bot/test_game_service.py -v`
Expected: PASS(アーカイブ文言 2 件を含め全件通過)

- [ ] **Step 7: import スモークで検証**

Run: `uv run python -c "import src.bot.game_service; print('ok')"`
Expected: `ok`(discord 依存の追加 import・async メソッドの構文健全性を確認)

- [ ] **Step 8: コミット**

```bash
git add src/bot/game_service.py tests/bot/test_game_service.py
git commit -m "feat: GameService に盤面投稿/更新/終了/タイマーとアーカイブ文言を追加"
```

---

## Task 2: /session_start cog

**Files:**
- Create: `src/cogs/session_start.py`

cog は薄いアダプタのため自動テストは import スモークのみとし、実挙動は末尾の手動結合テストで検証する。

- [ ] **Step 1: cog を実装**

`src/cogs/session_start.py` を新規作成する。

```python
from __future__ import annotations

import asyncio
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

from src.bot.client import GameBot

_PANEL_CHOICES = [
    app_commands.Choice(name="4 (2x2)", value=4),
    app_commands.Choice(name="9 (3x3)", value=9),
    app_commands.Choice(name="16 (4x4)", value=16),
    app_commands.Choice(name="25 (5x5)", value=25),
]
# value=0 は「しない」を表し、cog で None(モザイクなし)へ変換する。
_MOSAIC_CHOICES = [
    app_commands.Choice(name="しない", value=0),
    app_commands.Choice(name="弱", value=150),
    app_commands.Choice(name="中", value=90),
    app_commands.Choice(name="強", value=45),
    app_commands.Choice(name="最強", value=27),
]


class SessionStartCog(commands.Cog):
    """セッション開始コマンドを提供する cog。"""

    def __init__(self, bot: GameBot) -> None:
        """bot を保持して初期化する。

        Args:
            bot: コマンドを提供する GameBot。
        """
        self.bot = bot

    @app_commands.command(name="session_start", description="新しいセッションを開始する")
    @app_commands.describe(
        panels="盤面のパネル数(既定 9)",
        rotate="画像を回転する(既定しない)",
        grayscale="画像を白黒にする(既定しない)",
        mosaic="モザイクの強さ(既定しない)",
    )
    @app_commands.choices(panels=_PANEL_CHOICES, mosaic=_MOSAIC_CHOICES)
    async def session_start(
        self,
        interaction: discord.Interaction,
        panels: app_commands.Choice[int] | None = None,
        rotate: bool = False,
        grayscale: bool = False,
        mosaic: app_commands.Choice[int] | None = None,
    ) -> None:
        """セッションを開始し、盤面投稿・ピン留め・タイマー開始を行う。

        Args:
            interaction: コマンドのインタラクション。
            panels: パネル数の選択。未指定は 9。
            rotate: 回転するか。
            grayscale: 白黒にするか。
            mosaic: モザイク強度の選択。未指定/「しない」はモザイクなし。
        """
        game = self.bot.game
        if game.session is not None:
            await interaction.response.send_message(
                "既にセッションが進行中です。", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        panel_count = panels.value if panels is not None else 9
        mosaic_px = mosaic.value if mosaic is not None and mosaic.value else None
        game.start_session(
            panel_count=panel_count,
            rotate=rotate,
            grayscale=grayscale,
            mosaic_px=mosaic_px,
            now=datetime.now(),
        )
        await game.post_session_messages(interaction.channel)
        archive_channel = self.bot.get_channel(game.settings.archive_channel_id)
        game.timer_task = asyncio.create_task(
            game.run_timer(archive_channel, now=datetime.now())
        )
        await interaction.followup.send("セッションを開始しました。", ephemeral=True)


async def setup(bot: GameBot) -> None:
    """cog を bot へ登録する。

    Args:
        bot: 登録先の GameBot。
    """
    await bot.add_cog(SessionStartCog(bot))
```

- [ ] **Step 2: import スモークで検証**

Run: `uv run python -c "import src.cogs.session_start; print('ok')"`
Expected: `ok`

- [ ] **Step 3: コミット**

```bash
git add src/cogs/session_start.py
git commit -m "feat: /session_start cog を追加(盤面投稿・ピン・タイマー開始)"
```

---

## Task 3: /session_end cog

**Files:**
- Create: `src/cogs/session_end.py`

- [ ] **Step 1: cog を実装**

`src/cogs/session_end.py` を新規作成する。

```python
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from src.bot.client import GameBot


class SessionEndCog(commands.Cog):
    """セッション終了コマンドを提供する cog。"""

    def __init__(self, bot: GameBot) -> None:
        """bot を保持して初期化する。

        Args:
            bot: コマンドを提供する GameBot。
        """
        self.bot = bot

    @app_commands.command(name="session_end", description="セッションを終了しアーカイブする")
    async def session_end(self, interaction: discord.Interaction) -> None:
        """タイマーを止め、現時点の盤面をアーカイブして終了する。

        Args:
            interaction: コマンドのインタラクション。
        """
        game = self.bot.game
        if game.session is None:
            await interaction.response.send_message(
                "進行中のセッションがありません。", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        archive_channel = self.bot.get_channel(game.settings.archive_channel_id)
        game.cancel_timer()
        await game.end_session(archive_channel)
        await interaction.followup.send("セッションを終了しました。", ephemeral=True)


async def setup(bot: GameBot) -> None:
    """cog を bot へ登録する。

    Args:
        bot: 登録先の GameBot。
    """
    await bot.add_cog(SessionEndCog(bot))
```

- [ ] **Step 2: import スモークで検証**

Run: `uv run python -c "import src.cogs.session_end; print('ok')"`
Expected: `ok`

- [ ] **Step 3: コミット**

```bash
git add src/cogs/session_end.py
git commit -m "feat: /session_end cog を追加(アーカイブ・ピン解除・終了)"
```

---

## Task 4: /session_clear cog

**Files:**
- Create: `src/cogs/session_clear.py`

- [ ] **Step 1: cog を実装**

`src/cogs/session_clear.py` を新規作成する。

```python
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from src.bot.client import GameBot


class SessionClearCog(commands.Cog):
    """セッション強制破棄コマンドを提供する cog。"""

    def __init__(self, bot: GameBot) -> None:
        """bot を保持して初期化する。

        Args:
            bot: コマンドを提供する GameBot。
        """
        self.bot = bot

    @app_commands.command(
        name="session_clear", description="セッションをアーカイブせず強制終了する"
    )
    async def session_clear(self, interaction: discord.Interaction) -> None:
        """タイマーを止め、ピンを解除してアーカイブ無しで破棄する。

        Args:
            interaction: コマンドのインタラクション。
        """
        game = self.bot.game
        if game.session is None:
            await interaction.response.send_message(
                "進行中のセッションがありません。", ephemeral=True
            )
            return
        await game.clear_session()
        await interaction.response.send_message(
            "セッションを破棄しました。", ephemeral=True
        )


async def setup(bot: GameBot) -> None:
    """cog を bot へ登録する。

    Args:
        bot: 登録先の GameBot。
    """
    await bot.add_cog(SessionClearCog(bot))
```

- [ ] **Step 2: import スモークで検証**

Run: `uv run python -c "import src.cogs.session_clear; print('ok')"`
Expected: `ok`

- [ ] **Step 3: 全自動テストの回帰確認**

Run: `APP_ENV=test uv run pytest -q`
Expected: PASS(既存 + T1/T2 で追加したテストが全件通過)

- [ ] **Step 4: コミット**

```bash
git add src/cogs/session_clear.py
git commit -m "feat: /session_clear cog を追加(アーカイブ無し強制破棄)"
```

---

## 手動結合テスト(実機・自動化対象外)

`.env` に `DISCORD_TOKEN` / `GAME_GUILD_ID` / `ARCHIVE_CHANNEL_ID` を設定し、`uv run python -m src.main` で起動して確認する。

1. `/session_start panels:4` … 2×2 盤面画像とお題リストが投稿され、両方がピン留めされる。
2. 約 `session_duration_minutes - session_warning_minutes` 分後に予告メッセージが出る(短縮確認したい場合は `.env` で `SESSION_DURATION_MINUTES` / `SESSION_WARNING_MINUTES` を小さくする)。
3. `/session_end` … アーカイブ ch に現時点の盤面 + `||曲名||` + 正解者一覧が投稿され、ピンが解除される。終了後は `/session_start` が再度可能。
4. `/session_clear`(セッション中)… アーカイブ無しで破棄され、ピンが解除される。
5. セッションが無い状態で `/session_end` / `/session_clear` … ephemeral で「進行中のセッションがありません。」が返る。
6. セッション中に `/session_start` … ephemeral で「既にセッションが進行中です。」が返る。

---

## このタスクで実装しないこと(T3 へ委譲)

- `/report`(プレイ申告・お題照合・盤面開示・該当お題の公開 embed)。
- `/answer`(隠し曲の当て・正解者記録)。
- `/progress`(現在の盤面・お題進捗・残り時間の ephemeral 表示)。

`GameService.refresh_board` は本タスクで実装済みだが、開示を発生させる `/report` は T3 で初めて呼ぶ。

---

## Self-Review(立案者チェック結果)

- **スペック対応**: /session_start(panels/rotate/grayscale/mosaic・盤面投稿・ピン・30 分タイマー・予告)→ Task 2 + `run_timer`/`post_session_messages`(Task 1)。/session_end(現時点画像 + `||曲名||` + 正解者をアーカイブ・ピン解除)→ Task 3 + `end_session`/`format_archive_caption`(Task 1)。/session_clear(アーカイブ無し破棄)→ Task 4 + `clear_session`(Task 1)。コマンドガード(未/重複セッション)を各 cog で ephemeral 通知。
- **プレースホルダ無し**: 各ステップに実コード・実コマンド・期待結果を記載。
- **型整合**: `GameService.post_session_messages(channel)` / `refresh_board()` / `end_session(archive_channel)->GameSession` / `clear_session()` / `run_timer(archive_channel, *, now)` / プロパティ `settings->BaseAppSettings` / 定数 `BOARD_FILENAME` をタスク間・cog 間で一貫使用。cog は `self.bot.game`(`GameService`)・`self.bot.get_channel(...)` を使用。T1 の属性 `board_message`/`topic_message`/`timer_task` を discord 型へ付け替える点を Task 1 Step 3 で明示。
- **責務分離**: Discord I/O は GameService に集約し、`/session_end` と自動終了タイマーが同一の `end_session` を共有する。タイマー自走時の自己取り消しを避けるため `end_session` は `cancel_timer` を呼ばず、手動終了側(Task 3)が `cancel_timer` を呼ぶ設計を明記。
- **テスト切り分け**: Discord 非依存の `format_archive_caption` のみ TDD。投稿・編集・ピン・タイマー実走行・cog は import スモーク + 手動結合テストで検証(自動テスト基盤に discord モックを導入しない既存方針を踏襲)。
```
