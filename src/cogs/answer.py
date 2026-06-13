from __future__ import annotations

import discord
from discord import app_commands

from src.bot.client import GameBot
from src.cogs._song_input import SongCommandCog


class AnswerCog(SongCommandCog):
    """隠し曲の当てコマンドを提供する cog。"""

    @app_commands.command(name="answer", description="隠し曲を当てる")
    @app_commands.describe(song="曲名(部分一致)")
    @app_commands.autocomplete(song=SongCommandCog._song_autocomplete)
    async def answer(self, interaction: discord.Interaction, song: str) -> None:
        """隠し曲と照合し、正解なら回答者を記録する(全て ephemeral)。

        Args:
            interaction: コマンドのインタラクション。
            song: 曲名(部分一致)。
        """
        game = self.bot.game
        if await self._require_session_or_reply(interaction) is None:
            return
        resolved = await self._resolve_or_reply(interaction, song)
        if resolved is None:
            return
        correct = game.session_manager.record_answer(interaction.user.id, resolved)
        await interaction.response.send_message(
            "正解" if correct else "不正解", ephemeral=True
        )


async def setup(bot: GameBot) -> None:
    """cog を bot へ登録する。

    Args:
        bot: 登録先の GameBot。
    """
    await bot.add_cog(AnswerCog(bot))
