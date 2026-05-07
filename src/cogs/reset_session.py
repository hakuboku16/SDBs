"""
/reset スラッシュコマンドを定義するモジュール

ARCHITECTURE.md ステップ 5.4 に従い、進行中のセッションを強制リセットする処理を提供します:

1. 現セッションが無ければ ephemeral でその旨を返す (副作用無し)
2. ピン留めしたタスクメッセージのピンを解除する (失敗しても続行)
3. `SessionManager.reset()` でセッションとタイマーを破棄する
4. 呼び出しユーザーへ ephemeral で完了応答を返す

`/end` と異なり結果チャンネルへの投稿は行いません (要件: 強制クリア用途)。
ピン解除のみ Discord 依存処理が残るため、本 cog 内に閉じた静的ヘルパとして実装し
[`SessionFinalizer`](src/services/session_finalizer.py) には依存しません。
"""

import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from src.services.session_manager import SessionManager

# モジュールスコープのロガー (production では `__main__` 親ロガーから propagate)
logger = logging.getLogger(__name__)


# ==================================================
# /reset cog
# ==================================================
class ResetSessionCog(commands.Cog):
    """
    `/reset` スラッシュコマンドを提供する cog

    セッションが既に無い状態でも例外を送出せず ephemeral 応答だけで完了する設計です
    (`SessionManager.reset()` の「強制クリア」セマンティクスに合わせる)。
    """

    def __init__(self, bot: commands.Bot) -> None:
        """
        cog を初期化する

        Args:
            bot: 親 Bot インスタンス (`SDBsBot` を想定)
        """
        super().__init__()
        self.bot: commands.Bot = bot

    # --------------------------------------------------
    # スラッシュコマンド本体
    # --------------------------------------------------
    @app_commands.command(
        name="reset",
        description="進行中のセッションを強制リセットします (結果チャンネルへの投稿は行いません)",
    )
    async def reset(self, interaction: discord.Interaction) -> None:
        """
        進行中のセッションを強制リセットする

        - 現セッションが無い場合は ephemeral で通知して終了
        - 現セッションがある場合: ピン解除 → `SessionManager.reset()` → 完了応答
        - ピン解除に時間がかかり得るため成功パスでは ``defer`` で 3 秒応答制限を回避
        """
        manager: SessionManager = SessionManager.instance()
        session = manager.current()

        if session is None:
            await interaction.response.send_message(
                "進行中のセッションがありません。",
                ephemeral=True,
            )
            return

        # ピン解除に時間がかかり得るため defer (ephemeral)
        await interaction.response.defer(ephemeral=True)

        # ----- ピン解除 (失敗しても reset は続行) -----
        if session.pinned_message_id is not None:
            await self._unpin_message(
                interaction.channel, session.pinned_message_id
            )

        # ----- セッション破棄 (タイマーも cancel される) -----
        manager.reset()

        await interaction.followup.send(
            "セッションをリセットしました。",
            ephemeral=True,
        )

    # --------------------------------------------------
    # 内部ヘルパー
    # --------------------------------------------------
    @staticmethod
    async def _unpin_message(
        channel: Optional[discord.abc.Messageable], message_id: int
    ) -> None:
        """
        指定メッセージのピン解除を試みる。失敗時は warning に残し処理を継続する。

        `discord.abc.Messageable` 自体には `fetch_message` は定義されていないが、
        実装型 (TextChannel / Thread / DMChannel 等) は持つため `getattr` で取得する。
        要件「エラーは握りつぶさず、意味のあるメッセージ付きで処理する」に従い、
        失敗ケースは warning ログを残してから抜ける。
        """
        if channel is None:
            logger.warning(
                "チャンネルが取得できないためピン解除をスキップします (message_id=%s)",
                message_id,
            )
            return
        fetch = getattr(channel, "fetch_message", None)
        if not callable(fetch):
            logger.warning(
                "チャンネル (type=%s) は fetch_message をサポートしていないため"
                "ピン解除をスキップします",
                type(channel).__name__,
            )
            return
        try:
            message = await fetch(message_id)
            await message.unpin()
        except discord.DiscordException as e:
            logger.warning(
                "ピン解除に失敗しました (message_id=%s): %s", message_id, e
            )


# ==================================================
# extension エントリポイント
# ==================================================
async def setup(bot: commands.Bot) -> None:
    """
    `Bot.load_extension` から呼ばれる cog 登録関数

    `/reset` は外部依存を持たないため、cog 単独で構築・登録します。
    """
    cog = ResetSessionCog(bot)
    await bot.add_cog(cog)
