from __future__ import annotations

import discord
from discord import app_commands

from src.bot import embeds
from src.bot.client import GameBot
from src.cogs._base import GameCog


class SessionClearCog(GameCog):
    """セッション強制破棄コマンドを提供する cog。"""

    @app_commands.command(
        name="session_clear", description="セッションをアーカイブせず強制終了する"
    )
    async def session_clear(self, interaction: discord.Interaction) -> None:
        """タイマーを止め、ピンを解除してアーカイブ無しで破棄する。

        Args:
            interaction: コマンドのインタラクション。
        """
        game = self.bot.game
        if await self._require_session_or_reply(interaction) is None:
            return
        await game.clear_session()
        await interaction.response.send_message(
            embed=embeds.success("セッションを破棄しました。"), ephemeral=True
        )


async def setup(bot: GameBot) -> None:
    """cog を bot へ登録する。

    Args:
        bot: 登録先の GameBot。
    """
    await bot.add_cog(SessionClearCog(bot))
