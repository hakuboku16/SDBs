from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from src.bot.client import GameBot
from src.bot.game_service import AmbiguousSong, SongNotFound, format_completed_topics
from src.game.models import Difficulty, PlayReport

_DIFFICULTY_CHOICES = [
    app_commands.Choice(name="Easy", value="Easy"),
    app_commands.Choice(name="Normal", value="Normal"),
    app_commands.Choice(name="Hard", value="Hard"),
]


class SongReportCog(commands.Cog):
    """プレイ申告コマンドを提供する cog。"""

    def __init__(self, bot: GameBot) -> None:
        """bot を保持して初期化する。

        Args:
            bot: コマンドを提供する GameBot。
        """
        self.bot = bot

    async def _song_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """曲名候補を返す。セッション有無に関わらず全曲を対象にする。

        Args:
            interaction: オートコンプリートのインタラクション。
            current: 入力中の文字列。

        Returns:
            list[app_commands.Choice[str]]: 曲名候補(最大 25 件)。
        """
        return [
            app_commands.Choice(name=title, value=title)
            for title in self.bot.game.suggest_song_titles(current)
        ]

    @app_commands.command(name="report", description="プレイ結果を申告する")
    @app_commands.describe(
        song="曲名(部分一致)",
        difficulty="難易度",
        combo="獲得コンボ数",
        charming="獲得チャーミング数",
    )
    @app_commands.choices(difficulty=_DIFFICULTY_CHOICES)
    @app_commands.autocomplete(song=_song_autocomplete)
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
            embed = discord.Embed(
                title="お題達成", description=format_completed_topics(newly_completed)
            )
            await interaction.channel.send(embed=embed)
            await interaction.followup.send("申告を反映しました。", ephemeral=True)
        else:
            await interaction.followup.send(
                "申告を反映しました。達成したお題はありません。", ephemeral=True
            )


async def setup(bot: GameBot) -> None:
    """cog を bot へ登録する。

    Args:
        bot: 登録先の GameBot。
    """
    await bot.add_cog(SongReportCog(bot))
