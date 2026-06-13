from __future__ import annotations

from datetime import datetime
from io import BytesIO

import discord
from discord import app_commands

from src.bot.client import GameBot
from src.bot.game_service import BOARD_FILENAME, format_progress_text
from src.cogs._base import GameCog


class SessionProgressCog(GameCog):
    """現在状況表示コマンドを提供する cog。"""

    @app_commands.command(name="progress", description="現在の盤面と進捗を表示する")
    async def progress(self, interaction: discord.Interaction) -> None:
        """現在の盤面・お題進捗・残り時間を ephemeral で表示する。

        Args:
            interaction: コマンドのインタラクション。
        """
        game = self.bot.game
        session = await self._require_session_or_reply(interaction)
        if session is None:
            return
        await interaction.response.defer(ephemeral=True)
        remaining = game.session_manager.remaining(datetime.now())
        png = game.render_current_board()
        await interaction.followup.send(
            content=format_progress_text(session, remaining),
            file=discord.File(BytesIO(png), filename=BOARD_FILENAME),
            ephemeral=True,
        )


async def setup(bot: GameBot) -> None:
    """cog を bot へ登録する。

    Args:
        bot: 登録先の GameBot。
    """
    await bot.add_cog(SessionProgressCog(bot))
