from __future__ import annotations

import discord
from discord.ext import commands

from src.bot.client import GameBot
from src.game.models import GameSession


class GameCog(commands.Cog):
    """全 cog 共通の bot 保持とセッションガードを提供する cog 基底。

    bot 参照の保持と「アクティブセッションが無ければ ephemeral 応答」の定型処理を
    集約する。曲名を扱う cog は SongCommandCog 経由でこれを継承する。
    """

    def __init__(self, bot: GameBot) -> None:
        """bot を保持して初期化する。

        Args:
            bot: コマンドを提供する GameBot。
        """
        self.bot = bot

    async def _require_session_or_reply(
        self, interaction: discord.Interaction
    ) -> GameSession | None:
        """アクティブセッションを返す。無ければ ephemeral 応答して None を返す。

        Args:
            interaction: コマンドのインタラクション。未応答であること。

        Returns:
            GameSession | None: アクティブセッション。無ければ None。
        """
        session = self.bot.game.session
        if session is None:
            await interaction.response.send_message(
                "進行中のセッションがありません。", ephemeral=True
            )
        return session
