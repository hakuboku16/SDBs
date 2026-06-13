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
