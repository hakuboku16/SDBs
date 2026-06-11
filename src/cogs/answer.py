from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from src.bot.client import GameBot
from src.bot.game_service import AmbiguousSong, SongNotFound


class AnswerCog(commands.Cog):
    """隠し曲の当てコマンドを提供する cog。"""

    def __init__(self, bot: GameBot) -> None:
        """bot を保持して初期化する。

        Args:
            bot: コマンドを提供する GameBot。
        """
        self.bot = bot

    @app_commands.command(name="answer", description="隠し曲を当てる")
    @app_commands.describe(song="曲名(部分一致)")
    async def answer(self, interaction: discord.Interaction, song: str) -> None:
        """隠し曲と照合し、正解なら回答者を記録する(全て ephemeral)。

        Args:
            interaction: コマンドのインタラクション。
            song: 曲名(部分一致)。
        """
        game = self.bot.game
        if game.session is None:
            await interaction.response.send_message(
                "進行中のセッションがありません。", ephemeral=True
            )
            return
        try:
            resolved = game.resolve_song(song)
        except SongNotFound:
            await interaction.response.send_message(
                f"「{song}」に一致する曲が見つかりません。", ephemeral=True
            )
            return
        except AmbiguousSong as exc:
            names = "、".join(s.title for s in exc.matches[:10])
            await interaction.response.send_message(
                f"候補が複数あります。曲名を絞ってください: {names}", ephemeral=True
            )
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
