# M1 残り(bot 足場)実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Discord 層の足場(config 拡張・bot クライアント・cog ローダ・command sync・WARNING+ をログchへ送るハンドラ・bot 起動)を整え、テストギルドへ接続できる状態にする。

**Architecture:** ゲーム層(`src/game/`)は完成済みで Discord 非依存。本計画は M1 のうち未実装の「足場」のみを対象とする。cog 本体・サービス結線・アーカイブ・盤面投稿は M5 へ委譲する。テストは設計書が明記する config 既定値と、Discord 非依存に切り出せるログ転送判定(`should_forward`)のみを自動化し、bot 接続・コマンド同期・ログ着弾は手動結合テストで検証する(ユーザー合意)。

**Tech Stack:** Python 3.12 / uv / pytest / pydantic-settings(既存)/ discord.py(新規追加)

---

## 現状(着手前の事実)

- ゲーム層は完成・テスト済み: `models` / `song_repository` / `topic_catalog` / `topic_types` / `predicates` / `topic_generator` / `play_matcher` / `session_manager` / `board` / `image_options`。
- 未実装(本計画の対象):
  - [src/core/config.py](src/core/config.py) … ログ設定のみ。Discord/ゲーム設定が未追加。
  - [src/main.py](src/main.py) … `logger.info` のみで bot 起動なし。
  - `src/bot/`(client・discord_log_handler)が存在しない。
  - `src/cogs/` が存在しない(本計画では空パッケージのみ用意。cog 本体は M5)。
  - `discord.py` 依存が未追加。
- [src/core/logger.py](src/core/logger.py) は console+file ハンドラを持つ。本計画では変更しない(ログ送信ハンドラは bot 接続後に root へ直接追加する)。

## 実アセットパス(config 既定値の根拠)

- 楽曲: `assets/data/all_songs.json`
- お題: `assets/data/all_topics.json`
- 画像: `assets/images`

## ファイル構成

- 変更: `pyproject.toml`(discord.py 追加)
- 変更: `src/core/config.py`(`BaseAppSettings` へ Discord/ゲーム設定を追加)
- 変更: `tests/test_config.py`(新設定の既定値テストを追加)
- 変更: `.env.example`(新環境変数を追記)
- 作成: `src/bot/__init__.py`(空)
- 作成: `src/bot/discord_log_handler.py`(`should_forward` + `DiscordLogHandler`)
- 作成: `tests/test_discord_log_handler.py`(`should_forward` のテスト)
- 作成: `src/bot/client.py`(`GameBot`:cog ローダ・on_ready 同期・ログ転送起動)
- 作成: `src/cogs/__init__.py`(空。ローダの探索先)
- 変更: `src/main.py`(bot 構成・起動)

---

## Task 1: discord.py 追加 + config に Discord/ゲーム設定を追加

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/core/config.py:15-31`(`BaseAppSettings` 本体へフィールド追加)
- Test: `tests/test_config.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_config.py` の末尾へ追記する。

```python
def test_game_defaults() -> None:
    """Discord/ゲーム設定の既定値が想定どおりであることを確認する。"""
    # ローカル .env に実 token/ID が入っていても既定値を検証できるよう .env を無効化する。
    base = BaseAppSettings(app_env=AppEnv.DEVELOPMENT, _env_file=None)
    assert base.discord_token == ""
    assert base.game_guild_id == 0
    assert base.log_guild_id == 0
    assert base.log_channel_id == 0
    assert base.archive_channel_id == 0
    assert base.songs_data_path == "assets/data/all_songs.json"
    assert base.topics_data_path == "assets/data/all_topics.json"
    assert base.images_dir == "assets/images"
    assert base.session_duration_minutes == 30
    assert base.session_warning_minutes == 10
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `APP_ENV=test uv run pytest tests/test_config.py::test_game_defaults -v`
Expected: FAIL(`AttributeError: 'BaseAppSettings' object has no attribute 'discord_token'`)

- [ ] **Step 3: discord.py を依存へ追加**

Run: `uv add "discord.py>=2.4"`
Expected: `pyproject.toml` の `dependencies` に `"discord.py>=2.4"` が追加され、`uv.lock` が更新される。

- [ ] **Step 4: config へフィールドを追加**

[src/core/config.py](src/core/config.py) の `BaseAppSettings` で、既存の `log_backup_days` 行の直後へ追記する。

```python
    log_backup_days: int = 30

    # Discord(秘匿値・ID は .env 管理。既定は未設定相当)
    discord_token: str = ""
    game_guild_id: int = 0
    log_guild_id: int = 0
    log_channel_id: int = 0
    archive_channel_id: int = 0

    # データ/アセット
    songs_data_path: str = "assets/data/all_songs.json"
    topics_data_path: str = "assets/data/all_topics.json"
    images_dir: str = "assets/images"

    # セッション(分)
    session_duration_minutes: int = 30
    session_warning_minutes: int = 10
```

- [ ] **Step 5: テストが通ることを確認**

Run: `APP_ENV=test uv run pytest tests/test_config.py -v`
Expected: PASS(既存 config テスト含め全件通過)

- [ ] **Step 6: コミット**

```bash
git add pyproject.toml uv.lock src/core/config.py tests/test_config.py
git commit -m "feat: config に Discord/ゲーム設定を追加し discord.py を依存へ追加"
```

---

## Task 2: .env.example を更新

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: .env.example を書き換える**

[.env.example](.env.example) の内容を以下に置き換える。

```dotenv
# 環境切替(必須)
APP_ENV=development

# Discord(必須・秘匿)
DISCORD_TOKEN=
GAME_GUILD_ID=
LOG_GUILD_ID=
LOG_CHANNEL_ID=
ARCHIVE_CHANNEL_ID=
```

パス(`songs_data_path` / `topics_data_path` / `images_dir`)とセッション時間
(`session_duration_minutes` / `session_warning_minutes`)は config の既定値で管理するため
`.env.example` には載せない(センシティブ情報のみを .env で管理する方針)。

- [ ] **Step 2: コミット**

```bash
git add .env.example
git commit -m "docs: .env.example に Discord/ゲーム設定の変数を追記"
```

---

## Task 3: Discord ログ転送ハンドラ

**Files:**
- Create: `src/bot/__init__.py`
- Create: `src/bot/discord_log_handler.py`
- Test: `tests/test_discord_log_handler.py`

- [ ] **Step 1: bot パッケージの空 __init__ を作成**

`src/bot/__init__.py` を空ファイルとして作成する。

- [ ] **Step 2: 失敗するテストを書く**

`tests/test_discord_log_handler.py` を新規作成する。

```python
import logging

from src.bot.discord_log_handler import should_forward


def _record(name: str, level: int) -> logging.LogRecord:
    """テスト用の LogRecord を組み立てる。

    Args:
        name: ロガー名。
        level: ログレベル数値。

    Returns:
        logging.LogRecord: 指定名・レベルのレコード。
    """
    return logging.LogRecord(
        name=name,
        level=level,
        pathname=__file__,
        lineno=1,
        msg="m",
        args=(),
        exc_info=None,
    )


def test_forwards_warning_from_app_logger() -> None:
    """しきい値以上かつアプリ由来のレコードは転送対象になる。"""
    record = _record("src.cogs.session_start", logging.WARNING)
    assert should_forward(record, logging.WARNING) is True


def test_excludes_below_threshold() -> None:
    """しきい値未満のレコードは転送対象外になる。"""
    record = _record("src.app", logging.INFO)
    assert should_forward(record, logging.WARNING) is False


def test_excludes_discord_library_records() -> None:
    """discord ライブラリ由来のレコードはループ防止のため転送対象外になる。"""
    record = _record("discord.gateway", logging.ERROR)
    assert should_forward(record, logging.WARNING) is False
```

- [ ] **Step 3: テストが失敗することを確認**

Run: `APP_ENV=test uv run pytest tests/test_discord_log_handler.py -v`
Expected: FAIL(`ModuleNotFoundError: No module named 'src.bot.discord_log_handler'`)

- [ ] **Step 4: ハンドラを実装**

`src/bot/discord_log_handler.py` を新規作成する。

```python
from __future__ import annotations

import asyncio
import logging


def should_forward(record: logging.LogRecord, threshold: int) -> bool:
    """ログレコードを Discord ログチャンネルへ転送すべきか判定する。

    Args:
        record: 判定対象のログレコード。
        threshold: 転送する最小レベル(これ以上を転送する)。

    Returns:
        bool: threshold 以上の重大度で、かつ discord ライブラリ由来でなければ True。
    """
    # discord.* 由来を転送するとログch送信がさらにログを生み無限ループになるため除外する。
    if record.name.startswith("discord"):
        return False
    return record.levelno >= threshold


class DiscordLogHandler(logging.Handler):
    """WARNING 以上のログを asyncio キュー経由でログチャンネルへ送る Handler。

    emit はイベントループ外スレッドからも呼ばれ得るため、ここではキュー投入のみを
    call_soon_threadsafe で行い、実送信はループ上の消費タスクへ委ねる。
    """

    def __init__(
        self,
        queue: asyncio.Queue[str],
        loop: asyncio.AbstractEventLoop,
        level: int = logging.WARNING,
    ) -> None:
        """送信キューとイベントループを保持して初期化する。

        Args:
            queue: 整形済みログ文字列を渡す送信キュー。
            loop: キュー投入をスケジュールするイベントループ。
            level: 転送する最小ログレベル。
        """
        super().__init__(level)
        self._queue = queue
        self._loop = loop

    def emit(self, record: logging.LogRecord) -> None:
        """転送対象なら整形してキューへ投入する。

        Args:
            record: 出力対象のログレコード。
        """
        if not should_forward(record, self.level):
            return
        message = self.format(record)
        self._loop.call_soon_threadsafe(self._queue.put_nowait, message)
```

- [ ] **Step 5: テストが通ることを確認**

Run: `APP_ENV=test uv run pytest tests/test_discord_log_handler.py -v`
Expected: PASS(3 件通過)

- [ ] **Step 6: コミット**

```bash
git add src/bot/__init__.py src/bot/discord_log_handler.py tests/test_discord_log_handler.py
git commit -m "feat: WARNING+ をログchへ送る Discord ログハンドラを追加"
```

---

## Task 4: bot クライアント(GameBot)

**Files:**
- Create: `src/cogs/__init__.py`
- Create: `src/bot/client.py`

cog 本体は M5 のため、ここでは空の `src/cogs/` パッケージのみ用意する。ローダは存在する cog を全件ロードするが、本計画では 0 件ロードとなる。自動テストはインポート・スモークのみ(実接続は手動)。

- [ ] **Step 1: cogs 空パッケージを作成**

`src/cogs/__init__.py` を空ファイルとして作成する。

- [ ] **Step 2: client.py を実装**

`src/bot/client.py` を新規作成する。

```python
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import discord
from discord.ext import commands

from src.bot.discord_log_handler import DiscordLogHandler
from src.core.config import BaseAppSettings

logger = logging.getLogger(__name__)

_COGS_PACKAGE = "src.cogs"


class GameBot(commands.Bot):
    """アタック25 bot 本体。cog をロードし、起動時にコマンドを同期する。"""

    def __init__(self, settings: BaseAppSettings) -> None:
        """設定を保持し、アプリコマンド用の最小 intents で初期化する。

        Args:
            settings: アプリ設定(token・guild/channel ID 等)。
        """
        # app_commands のみ使うため prefix コマンドは使わないが、Bot は prefix 必須のため形式値を渡す。
        super().__init__(command_prefix="!", intents=discord.Intents.default())
        self._settings = settings
        self._log_queue: asyncio.Queue[str] = asyncio.Queue()
        self._log_started = False

    async def setup_hook(self) -> None:
        """接続前に cogs パッケージ配下の全 cog をロードする。"""
        await self._load_cogs()

    async def _load_cogs(self) -> None:
        """src/cogs 配下の各モジュールを extension としてロードする。"""
        cogs_dir = Path(__file__).resolve().parent.parent / "cogs"
        for path in sorted(cogs_dir.glob("*.py")):
            if path.stem == "__init__":
                continue
            await self.load_extension(f"{_COGS_PACKAGE}.{path.stem}")

    async def on_ready(self) -> None:
        """ギルドへコマンドを同期し、Discord ログ転送を開始する。

        再接続で複数回発火し得るため、同期とログ転送起動は冪等に行う。
        """
        guild = discord.Object(id=self._settings.game_guild_id)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        self._start_log_forwarding()
        logger.info("bot ready: %s", self.user)

    def _start_log_forwarding(self) -> None:
        """WARNING 以上をログchへ転送するハンドラと消費タスクを起動する(冪等)。"""
        # on_ready は再接続で再発火するため、ハンドラ二重登録とタスク多重起動を防ぐ。
        if self._log_started:
            return
        self._log_started = True
        loop = asyncio.get_running_loop()
        handler = DiscordLogHandler(self._log_queue, loop)
        handler.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
        logging.getLogger().addHandler(handler)
        loop.create_task(self._consume_log_queue())

    async def _consume_log_queue(self) -> None:
        """ログキューを順次ログチャンネルへ送信する。"""
        channel = self.get_channel(self._settings.log_channel_id)
        if not isinstance(channel, discord.TextChannel):
            logger.warning("log channel %s not found", self._settings.log_channel_id)
            return
        while True:
            message = await self._log_queue.get()
            await channel.send(f"```\n{message}\n```")
```

- [ ] **Step 3: インポート・スモークで検証**

Run: `uv run python -c "import src.bot.client; print('ok')"`
Expected: `ok`(構文・依存・import の健全性を確認。discord.py が解決されること)

- [ ] **Step 4: コミット**

```bash
git add src/cogs/__init__.py src/bot/client.py
git commit -m "feat: cog ローダと command sync を備えた GameBot を追加"
```

---

## Task 5: main.py で bot を起動

**Files:**
- Modify: `src/main.py`

- [ ] **Step 1: main.py を書き換える**

[src/main.py](src/main.py) の内容を以下に置き換える。

```python
import logging

from src.bot.client import GameBot
from src.core.config import settings
from src.core.logger import setup_logger


def main() -> None:
    """bot を構成して起動する。

    ロガーを初期化し、設定の token で GameBot を起動する。
    token 未設定なら警告を出して起動を中止する。
    """
    setup_logger()
    logger = logging.getLogger(__name__)
    if not settings.discord_token:
        logger.warning("discord_token is not set; aborting startup")
        return
    bot = GameBot(settings)
    # discord.py の既定ログ設定(basicConfig 相当)で自前ハンドラを上書きさせない。
    bot.run(settings.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: インポート・スモークで検証**

Run: `uv run python -c "import src.main; print('ok')"`
Expected: `ok`

- [ ] **Step 3: 全自動テストの回帰確認**

Run: `APP_ENV=test uv run pytest -q`
Expected: PASS(既存 + 本計画で追加したテストが全件通過)

- [ ] **Step 4: コミット**

```bash
git add src/main.py
git commit -m "feat: main で GameBot を構成し起動する"
```

---

## 手動結合テスト(実機・自動化対象外)

token と各 ID を `.env` に設定して確認する(ユーザーが実施)。

1. テストギルドの `.env` を用意: `DISCORD_TOKEN` / `GAME_GUILD_ID` / `LOG_CHANNEL_ID` を設定。
2. 起動: `uv run python -m src.main`
3. 期待: bot がオンラインになり、ログに `bot ready: <bot名>` が出る(エラーなく接続)。
4. コマンド同期: `tree.sync` が例外なく完了する(本計画では登録コマンドが 0 件のため一覧は空。コマンド表示の完全検証は M5)。
5. ログ着弾: 一時的に `logging.getLogger("src.manual").warning("test")` 等で WARNING を発生させ、`LOG_CHANNEL_ID` のチャンネルへ整形メッセージが届くことを確認する。`discord.*` 由来ログが転送されない(ループしない)ことも確認する。

---

## このマイルストーンで実装しないこと(M5 へ委譲)

- 6 つの cog 本体(`session_start` / `session_end` / `session_progress` / `session_clear` / `song_report` / `answer`)。本計画は空の `src/cogs/` パッケージのみ用意する。
- 共有サービスの結線(`SongRepository`・お題テンプレート・`SessionManager`・`board` の bot への注入と DI)。
- セッション終了アーカイブ・正解者発表・`/report` の該当お題 embed・盤面投稿/ピン留め/`message.edit` 差し替え。
- アプリコマンド共通エラーハンドラ。
- 「コマンド表示」の完全検証(cog が存在する M5 で実施)。

---

## Self-Review(立案者チェック結果)

- **スペック対応**: 設計書 §設定(新フィールド)→ Task 1、§.env → Task 2、§Discord ロギング(asyncio キュー・`call_soon_threadsafe`・`discord.*` 除外)→ Task 3、bot/client・cog ローダ・command sync(M1 §150)→ Task 4、bot 起動(main 改修)→ Task 5。config 既定値テスト(§テスト戦略)→ Task 1。M1 のうち本計画対象外(cog 結線)は M5 として明記。
- **プレースホルダ無し**: 各ステップに実コード/実コマンド/期待結果を記載。
- **型整合**: `GameBot(settings: BaseAppSettings)`、`DiscordLogHandler(queue, loop, level)`、`should_forward(record, threshold)` をタスク間で一貫使用。`settings` は [config.py](src/core/config.py) の `settings`(`BaseAppSettings` 派生)を渡す。
- **既定値の根拠**: 実アセットパス(`assets/data/all_songs.json` 等)を確認済み。`_env_file=None` で実 `.env` に依存しない既定値テストにしている。
