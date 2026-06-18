from __future__ import annotations

import discord
from discord import app_commands

from src.bot import embeds
from src.bot.client import GameBot
from src.bot.game_service import format_panel_list
from src.cogs._song_input import SongCommandCog
from src.game.models import Difficulty, PlayReport

_DIFFICULTY_CHOICES = [
    app_commands.Choice(name="Easy", value="Easy"),
    app_commands.Choice(name="Normal", value="Normal"),
    app_commands.Choice(name="Hard", value="Hard"),
    app_commands.Choice(name="Extra", value="Extra"),
]


class SongReportCog(SongCommandCog):
    """プレイ申告コマンドを提供する cog。"""

    @app_commands.command(name="play", description="プレイ結果を申告する")
    @app_commands.describe(
        song="曲名(部分一致)",
        difficulty="難易度",
        combo="獲得コンボ数",
        charming="獲得チャーミング数",
    )
    @app_commands.choices(difficulty=_DIFFICULTY_CHOICES)
    @app_commands.autocomplete(song=SongCommandCog._song_autocomplete)
    async def play(
        self,
        interaction: discord.Interaction,
        song: str,
        difficulty: app_commands.Choice[str],
        combo: int,
        charming: int,
    ) -> None:
        """申告を全お題へ照合し、該当パネルを開示して公開表示する。

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
        chart = resolved.charts.get(Difficulty(difficulty.value))
        if chart is None:
            await interaction.response.send_message(
                embed=embeds.warning(
                    f"「{resolved.title}」に {difficulty.value} の譜面がありません。"
                ),
                ephemeral=True,
            )
            return
        if combo > chart.notes or charming > chart.notes:
            await interaction.response.send_message(
                embed=embeds.warning(
                    f"入力されたノーツ数が {resolved.title} の {difficulty.value}"
                    f"(総ノーツ数 {chart.notes})を上回っています。"
                ),
                ephemeral=True,
            )
            return
        await interaction.response.defer()
        report = PlayReport(
            song=resolved,
            difficulty=Difficulty(difficulty.value),
            combo=combo,
            charming=charming,
        )
        applied = game.session_manager.apply_report(report)
        await game.refresh_board()
        body = (
            format_panel_list(applied) if applied else "進捗のあったタスクはありません。"
        )
        await interaction.followup.send(
            embed=embeds.success(body, title=f"▶ プレイ記録を追加: {resolved.title}")
        )


async def setup(bot: GameBot) -> None:
    """cog を bot へ登録する。

    Args:
        bot: 登録先の GameBot。
    """
    await bot.add_cog(SongReportCog(bot))
