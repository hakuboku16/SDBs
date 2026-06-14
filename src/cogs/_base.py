from __future__ import annotations

import discord
from discord.ext import commands

from src.bot.client import GameBot
from src.game.models import GameSession


class GameCog(commands.Cog):
    """全 cog 共通の bot 保持とセッションガードを提供する cog 基底。

    bot 参照の保持と「アクティブセッションが無ければ ephemeral 応答」の定型処理を
    集約する。曲名を扱う cog は SongCommandCog 経由でこれを継承する。
    """

    def __init__(self, bot: GameBot) -> None:
        """bot を保持して初期化する。

        Args:
            bot: コマンドを提供する GameBot。
        """
        self.bot = bot

    async def _require_session_or_reply(
        self, interaction: discord.Interaction
    ) -> GameSession | None:
        """アクティブセッションを返す。無ければ ephemeral 応答して None を返す。

        Args:
            interaction: コマンドのインタラクション。未応答であること。

        Returns:
            GameSession | None: アクティブセッション。無ければ None。
        """
        session = self.bot.game.session
        if session is None:
            await interaction.response.send_message(
                "進行中のセッションがありません。", ephemeral=True
            )
        return session

    async def _require_command_channel_or_reply(
        self, interaction: discord.Interaction
    ) -> discord.abc.Messageable | None:
        """コマンド実行チャンネルを送信可能チャンネルとして返す。

        Args:
            interaction: コマンドのインタラクション。defer 済みであること。

        Returns:
            discord.abc.Messageable | None: 送信可能な実行チャンネル。
                取得できない/送信不可なら ephemeral 応答して None を返す。
        """
        channel = interaction.channel
        if isinstance(channel, discord.abc.Messageable):
            return channel
        await interaction.followup.send(
            "このチャンネルには投稿できません。", ephemeral=True
        )
        return None

    async def _require_archive_channel_or_reply(
        self, interaction: discord.Interaction
    ) -> discord.abc.Messageable | None:
        """設定のアーカイブ用チャンネルを送信可能チャンネルとして返す。

        Args:
            interaction: コマンドのインタラクション。defer 済みであること。

        Returns:
            discord.abc.Messageable | None: 送信可能なアーカイブチャンネル。
                未解決/送信不可なら ephemeral 応答して None を返す。
        """
        channel = self.bot.get_channel(self.bot.game.settings.archive_channel_id)
        if isinstance(channel, discord.abc.Messageable):
            return channel
        await interaction.followup.send(
            "アーカイブ用チャンネルを取得できませんでした。設定を確認してください。",
            ephemeral=True,
        )
        return None
