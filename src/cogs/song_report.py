from __future__ import annotations

import discord
from discord import app_commands

from src.bot import embeds
from src.bot.client import GameBot
from src.bot.game_service import format_completed_topics
from src.cogs._song_input import SongCommandCog
from src.game.models import Difficulty, PlayReport

_DIFFICULTY_CHOICES = [
    app_commands.Choice(name="Easy", value="Easy"),
    app_commands.Choice(name="Normal", value="Normal"),
    app_commands.Choice(name="Hard", value="Hard"),
]


class SongReportCog(SongCommandCog):
    """プレイ申告コマンドを提供する cog。"""

    @app_commands.command(name="report", description="プレイ結果を申告する")
    @app_commands.describe(
        song="曲名(部分一致)",
        difficulty="難易度",
        combo="獲得コンボ数",
        charming="獲得チャーミング数",
    )
    @app_commands.choices(difficulty=_DIFFICULTY_CHOICES)
    @app_commands.autocomplete(song=SongCommandCog._song_autocomplete)
    async def report(
        self,
        interaction: discord.Interaction,
        song: str,
        difficulty: app_commands.Choice[str],
        combo: int,
        charming: int,
    ) -> None:
        """申告を全お題へ照合し、達成パネルを開示して公開表示する。

        Args:
            interaction: コマンドのインタラクション。
            song: 曲名(部分一致)。
            difficulty: 難易度の選択。
            combo: 獲得コンボ数。
            charming: 獲得チャーミング数。
        """
        game = self.bot.game
        if await self._require_session_or_reply(interaction) is None:
            return
        resolved = await self._resolve_or_reply(interaction, song)
        if resolved is None:
            return
        await interaction.response.defer(ephemeral=True)
        report = PlayReport(
            song=resolved,
            difficulty=Difficulty(difficulty.value),
            combo=combo,
            charming=charming,
        )
        newly_completed = game.session_manager.apply_report(report)
        await game.refresh_board()
        if newly_completed:
            channel = await self._require_command_channel_or_reply(interaction)
            if channel is None:
                return
            await channel.send(
                embed=embeds.success(
                    format_completed_topics(newly_completed), title="お題達成"
                )
            )
            await interaction.followup.send(
                embed=embeds.success("申告を反映しました。"), ephemeral=True
            )
        else:
            await interaction.followup.send(
                embed=embeds.info("申告を反映しました。達成したお題はありません。"),
                ephemeral=True,
            )


async def setup(bot: GameBot) -> None:
    """cog を bot へ登録する。

    Args:
        bot: 登録先の GameBot。
    """
    await bot.add_cog(SongReportCog(bot))
