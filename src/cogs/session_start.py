from __future__ import annotations

import asyncio
from datetime import datetime

import discord
from discord import app_commands

from src.bot import embeds
from src.bot.client import GameBot
from src.bot.game_service import MOSAIC_OPTIONS, mosaic_choice_label
from src.cogs._base import GameCog

_PANEL_CHOICES = [
    app_commands.Choice(name="4 (2x2)", value=4),
    app_commands.Choice(name="9 (3x3)", value=9),
    app_commands.Choice(name="16 (4x4)", value=16),
    app_commands.Choice(name="25 (5x5)", value=25),
]
# value=0 は「なし」を表し、cog で None(モザイクなし)へ変換する。ラベルには実効解像度 px を併記する。
_MOSAIC_CHOICES = [
    app_commands.Choice(name=mosaic_choice_label(name, px), value=px)
    for name, px in MOSAIC_OPTIONS
]


class SessionStartCog(GameCog):
    """セッション開始コマンドを提供する cog。"""

    @app_commands.command(name="session_start", description="新しいセッションを開始する")
    @app_commands.describe(
        panels="盤面のパネル数(既定 9)",
        rotate="画像を回転する(既定しない)",
        grayscale="画像を白黒にする(既定しない)",
        mosaic="モザイクの強さ(既定しない)",
    )
    @app_commands.choices(panels=_PANEL_CHOICES, mosaic=_MOSAIC_CHOICES)
    async def session_start(
        self,
        interaction: discord.Interaction,
        panels: app_commands.Choice[int] | None = None,
        rotate: bool = False,
        grayscale: bool = False,
        mosaic: app_commands.Choice[int] | None = None,
    ) -> None:
        """セッションを開始し、盤面投稿・ピン留め・タイマー開始を行う。

        Args:
            interaction: コマンドのインタラクション。
            panels: パネル数の選択。未指定は 9。
            rotate: 回転するか。
            grayscale: 白黒にするか。
            mosaic: モザイク強度の選択。未指定/「しない」はモザイクなし。
        """
        game = self.bot.game
        if game.session is not None:
            await interaction.response.send_message(
                embed=embeds.warning("既にセッションが進行中です。"), ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        channel = await self._require_command_channel_or_reply(interaction)
        if channel is None:
            return
        archive_channel = await self._require_archive_channel_or_reply(interaction)
        if archive_channel is None:
            return
        panel_count = panels.value if panels is not None else 9
        mosaic_px = mosaic.value if mosaic is not None and mosaic.value else None
        game.start_session(
            panel_count=panel_count,
            rotate=rotate,
            grayscale=grayscale,
            mosaic_px=mosaic_px,
            now=datetime.now(),
        )
        await game.post_session_messages(channel)
        game.timer_task = asyncio.create_task(
            game.run_timer(archive_channel, now=datetime.now())
        )
        await interaction.followup.send(embed=embeds.success("セッションを開始しました。"), ephemeral=True)


async def setup(bot: GameBot) -> None:
    """cog を bot へ登録する。

    Args:
        bot: 登録先の GameBot。
    """
    await bot.add_cog(SessionStartCog(bot))
