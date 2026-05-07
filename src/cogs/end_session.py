"""
/end スラッシュコマンドを定義するモジュール

ARCHITECTURE.md ステップ 5.3 に従い、進行中のセッションを手動終了する処理を提供します:

1. 現セッションが無ければ ephemeral でエラー応答 (二重 /end / セッション未開始対策)
2. `SessionFinalizer.finalize` で結果通知 (embed) → ピン解除 → セッション破棄を実行
3. 呼び出しユーザーへ ephemeral で完了応答を返す

`SessionFinalizer` は `/start` の自動終了タイマーからも利用される共通サービスです
([src/services/session_finalizer.py](src/services/session_finalizer.py))。
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from src.cogs._helpers import build_error_embed, build_success_embed
from src.services.image_processor import ImageProcessor
from src.services.session_finalizer import SessionFinalizer
from src.services.session_manager import SessionManager
from src.services.song_repository import SongRepository
from src.core.config import get_assets_config

# モジュールスコープのロガー (production では `__main__` 親ロガーから propagate)
logger = logging.getLogger(__name__)


# ==================================================
# /end cog
# ==================================================
class EndSessionCog(commands.Cog):
    """
    `/end` スラッシュコマンドを提供する cog

    依存はコンストラクタで注入し、テスト時は mock を差し込めるようにします。
    `setup()` 関数が `Config` 経由で実装の依存を構築し、Bot に登録します。
    """

    def __init__(
        self,
        bot: commands.Bot,
        *,
        session_finalizer: SessionFinalizer,
    ) -> None:
        """
        cog を初期化する

        Args:
            bot: 親 Bot インスタンス (`SDBsBot` を想定)。`bot.notifier` を結果通知に使う
            session_finalizer: セッション終了処理 (`/start` の自動終了とロジック共有)
        """
        super().__init__()
        self.bot: commands.Bot = bot
        self._session_finalizer: SessionFinalizer = session_finalizer

    # --------------------------------------------------
    # スラッシュコマンド本体
    # --------------------------------------------------
    @app_commands.command(
        name="end",
        description="進行中のセッションを終了します",
    )
    async def end(self, interaction: discord.Interaction) -> None:
        """
        進行中のセッションを終了する

        - セッションが無い場合は ephemeral でエラー応答 (defer しない)
        - 結果通知 + ピン解除 + セッション破棄を `SessionFinalizer` に委譲
        - 完了後はユーザーに ephemeral で「終了しました」と応答する

        画像合成と embed 送信に時間がかかる可能性があるため、成功パスでは ``defer`` で
        Discord の 3 秒応答制限を回避します。
        """
        manager: SessionManager = SessionManager.instance()
        session = manager.current()
        if session is None:
            await interaction.response.send_message(
                embed=build_error_embed(
                    "進行中のセッションがありません。/start で新しいセッションを開始してください。"
                ),
                ephemeral=True,
            )
            return

        # チャンネル取得 (ピン解除に必要)
        channel = interaction.channel
        if channel is None:
            # 通常 Slash Command はチャンネル付きで届くはずだが、念のため握りつぶさず警告
            await interaction.response.send_message(
                embed=build_error_embed("チャンネル外では実行できません。"),
                ephemeral=True,
            )
            return

        # 画像合成 + 結果通知に時間がかかり得るため defer
        await interaction.response.defer(ephemeral=True)

        # SessionFinalizer.finalize はチャンネルに `discord.abc.Messageable` 互換を要求するため
        # InteractionChannel (Union) のうち送受信可能な実装が来る前提で渡す
        await self._session_finalizer.finalize(
            session,
            channel,  # type: ignore[arg-type]
            getattr(self.bot, "notifier", None),
            summary="セッション終了",
        )

        await interaction.followup.send(
            embed=build_success_embed(
                f"セッションを終了しました (楽曲: {session.song_name})。"
            ),
            ephemeral=True,
        )


# ==================================================
# extension エントリポイント
# ==================================================
async def setup(bot: commands.Bot) -> None:
    """
    `Bot.load_extension` から呼ばれる cog 登録関数

    実行時の依存 (`SessionFinalizer`) を構築して cog に注入します。
    `SessionFinalizer` は内部で `ImageProcessor` を保持するため、本 cog 用に
    新しいインスタンスを構築します (cog 間で共有しなくても整合性は取れる設計)。
    """
    assets = get_assets_config()
    song_repository = SongRepository(
        songs_json=assets.songs_json,
        images_dir=assets.images_dir,
    )
    image_processor = ImageProcessor(song_repository=song_repository)
    session_finalizer = SessionFinalizer(image_processor=image_processor)

    cog = EndSessionCog(bot, session_finalizer=session_finalizer)
    await bot.add_cog(cog)
