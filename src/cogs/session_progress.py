from __future__ import annotations

from datetime import datetime
from io import BytesIO

import discord
from discord import app_commands
from discord.ext import commands

from src.bot.client import GameBot
from src.bot.game_service import BOARD_FILENAME, format_progress_text


class SessionProgressCog(commands.Cog):
    """現在状況表示コマンドを提供する cog。"""

    def __init__(self, bot: GameBot) -> None:
        """bot を保持して初期化する。

        Args:
            bot: コマンドを提供する GameBot。
        """
        self.bot = bot

    @app_commands.command(name="progress", description="現在の盤面と進捗を表示する")
    async def progress(self, interaction: discord.Interaction) -> None:
        """現在の盤面・お題進捗・残り時間を ephemeral で表示する。

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
        remaining = game.session_manager.remaining(datetime.now())
        png = game.render_current_board()
        await interaction.followup.send(
            content=format_progress_text(game.session, remaining),
            file=discord.File(BytesIO(png), filename=BOARD_FILENAME),
            ephemeral=True,
        )


async def setup(bot: GameBot) -> None:
    """cog を bot へ登録する。

    Args:
        bot: 登録先の GameBot。
    """
    await bot.add_cog(SessionProgressCog(bot))
