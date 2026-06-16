from __future__ import annotations

import discord
from discord import app_commands

from src.bot import embeds
from src.bot.game_service import AmbiguousSong, SongNotFound
from src.cogs._base import GameCog
from src.game.models import Song


class SongCommandCog(GameCog):
    """曲名のオートコンプリートと部分一致解決を共有する cog 基底。

    曲名を受け取る cog(answer/report)はこれを継承し、候補提示と解決失敗時の
    ephemeral 応答を共通化する。app_commands.autocomplete のコールバックは
    第 1 引数に Cog を要求するため、mixin ではなく Cog 基底として提供する。
    """

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

    async def _resolve_or_reply(
        self, interaction: discord.Interaction, song: str
    ) -> Song | None:
        """曲名を 1 件に解決する。失敗時は ephemeral 応答して None を返す。

        Args:
            interaction: コマンドのインタラクション。未応答であること。
            song: 解決対象の曲名(部分一致)。

        Returns:
            Song | None: 一意に解決できた曲。解決に失敗した場合は None。
        """
        try:
            return self.bot.game.resolve_song(song)
        except SongNotFound:
            await interaction.response.send_message(
                embed=embeds.error(f"「{song}」に一致する曲が見つかりません。"),
                ephemeral=True,
            )
        except AmbiguousSong as exc:
            names = "、".join(s.title for s in exc.matches[:10])
            await interaction.response.send_message(
                embed=embeds.warning(
                    f"候補が複数あります。曲名を絞ってください: {names}"
                ),
                ephemeral=True,
            )
        return None
