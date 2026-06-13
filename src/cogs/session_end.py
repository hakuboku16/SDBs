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
