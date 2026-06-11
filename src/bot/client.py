from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import discord
from discord.ext import commands

from discord import app_commands

from src.bot.game_service import GENERIC_ERROR_MESSAGE, GameService
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
        self.game = GameService.from_settings(settings)

    async def setup_hook(self) -> None:
        """接続前に cog をロードし、アプリコマンド共通エラーハンドラを結線する。"""
        await self._load_cogs()
        self.tree.on_error = self._on_app_command_error

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
