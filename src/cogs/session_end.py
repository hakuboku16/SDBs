from __future__ import annotations

import discord
from discord import app_commands

from src.bot import embeds
from src.bot.client import GameBot
from src.bot.game_service import SESSION_END_MESSAGE, SESSION_END_TITLE
from src.cogs._base import GameCog


class SessionEndCog(GameCog):
    """セッション終了コマンドを提供する cog。"""

    @app_commands.command(
        name="session_end", description="セッションを終了しアーカイブする"
    )
    async def session_end(self, interaction: discord.Interaction) -> None:
        """タイマーを止め、現時点の盤面をアーカイブして終了する。

        Args:
            interaction: コマンドのインタラクション。
        """
        game = self.bot.game
        if await self._require_session_or_reply(interaction) is None:
            return
        await interaction.response.defer(ephemeral=True)
        archive_channel = await self._require_archive_channel_or_reply(interaction)
        if archive_channel is None:
            return
        game.cancel_timer()
        await game.end_session(archive_channel)
        await interaction.followup.send(
            embed=embeds.neutral(SESSION_END_MESSAGE, title=SESSION_END_TITLE),
            ephemeral=True,
        )


async def setup(bot: GameBot) -> None:
    """cog を bot へ登録する。

    Args:
        bot: 登録先の GameBot。
    """
    await bot.add_cog(SessionEndCog(bot))
