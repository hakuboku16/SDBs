"""
セッション終了処理を共通化するモジュール

`/end` (手動終了) と `/start` から登録される自動終了タイマー (時間切れ) は、いずれも
以下の同一の後処理を必要とします:

1. 現状のクリア状況で最終パネル画像を再合成する
2. 結果チャンネルへ embed (マスク済み楽曲名 + 画像 + 正解者一覧) を投稿する
3. ピン留めしたタスクメッセージのピンを解除する
4. `SessionManager` からセッションを破棄しタイマーをキャンセルする

`SessionFinalizer` はこれらの手順をひとつのトランザクション的単位として提供し、
`StartSessionCog` (自動終了) と `EndSessionCog` (手動終了) で共有します。

設計判断:
    - Discord 依存 (チャンネル取得・送信) は呼び出し側 cog から渡す
      (`channel`, `notifier`) ことで、サービス自体は cog に依存しない
    - 二重終了防止のため、`SessionManager.is_active()` が False ならば全処理を no-op
      にする。これにより自動終了タイマー満了時に既に手動 /end が走っていたケース等の
      競合状況でも安全に再呼び出し可能 (冪等)。
"""

import logging
from typing import Optional

import discord

from src.services.discord_notifier import DiscordNotifier
from src.services.image_processor import ImageProcessor
from src.services.session import Session
from src.services.session_manager import SessionManager

# モジュールスコープのロガー (production では `__main__` 親ロガーから propagate)
logger = logging.getLogger(__name__)


# ==================================================
# SessionFinalizer
# ==================================================
class SessionFinalizer:
    """
    セッション終了に伴う後処理 (結果通知 / ピン解除 / セッション破棄) を集約するサービス

    Discord 依存処理 (チャンネルメソッド呼び出し) は引数として受け取り、本クラス自身は
    `discord.Client` を保持しません。これによりテストでは `MagicMock` の channel /
    notifier を渡すだけで終了処理の各ステップを検証できます。
    """

    def __init__(self, image_processor: ImageProcessor) -> None:
        """
        後処理サービスを初期化する

        Args:
            image_processor: 最終画像合成に用いる `ImageProcessor`
        """
        self._image_processor: ImageProcessor = image_processor

    # --------------------------------------------------
    # 公開 API
    # --------------------------------------------------
    async def finalize(
        self,
        session: Session,
        channel: discord.abc.Messageable,
        notifier: Optional[DiscordNotifier],
        *,
        summary: Optional[str] = None,
    ) -> None:
        """
        セッションを終了させ後処理を実行する

        手順:
            1. `SessionManager.is_active()` が False なら何もしない (二重終了防止)
            2. 現セッションのクリア状況で最終画像を合成 (失敗時は warning ログのみ)
            3. `notifier.notify_session_result` で embed を結果チャンネルへ送信
            4. `session.pinned_message_id` が存在すればピン解除
            5. `SessionManager.end()` でセッションを破棄しタイマーをキャンセル

        Args:
            session: 終了対象のセッション
            channel: ピン解除対象のメッセージが存在するチャンネル
            notifier: 結果通知に使うラッパ。`None` の場合は通知をスキップして警告を残す
            summary: embed description に出す補足文 (例: "セッション終了 (時間切れ)")
        """
        manager: SessionManager = SessionManager.instance()
        if not manager.is_active():
            return

        # ----- 最終画像合成 (現状のクリア済みパネルを反映) -----
        final_image = self._compose_final_image(session)

        # ----- 結果チャンネルへ通知 -----
        if notifier is None:
            logger.warning(
                "DiscordNotifier 未初期化のため結果通知をスキップします"
            )
        elif final_image is not None:
            await notifier.notify_session_result(
                image=final_image,
                masked_song_name=self.mask_song_name(session.song_name),
                correct_answerers=session.correct_answerers,
                summary=summary,
            )

        # ----- ピン解除 -----
        if session.pinned_message_id is not None:
            await self._unpin_message(channel, session.pinned_message_id)

        # ----- セッション破棄 -----
        manager.end()

    # --------------------------------------------------
    # 内部ヘルパー
    # --------------------------------------------------
    def _compose_final_image(self, session: Session):
        """
        現状のクリア状況を反映した最終画像を合成する

        合成失敗 (画像ファイル欠落 / 不正な引数) は致命的ではないため warning ログだけ
        残して `None` を返し、結果通知はスキップする。要件「エラーは握りつぶさず、
        意味のあるメッセージ付きで処理する」に従う。
        """
        try:
            return self._image_processor.compose(
                song_name=session.song_name,
                panel_count=session.panel_count,
                cleared_indices=session.cleared_panel_indices(),
                rotate=session.rotate,
                grayscale=session.grayscale,
                mosaic_block=session.mosaic_block,
            )
        except (FileNotFoundError, ValueError) as e:
            logger.warning("セッション終了時の画像合成に失敗しました: %s", e)
            return None

    @staticmethod
    async def _unpin_message(
        channel: discord.abc.Messageable, message_id: int
    ) -> None:
        """
        指定メッセージのピンを解除する。失敗時は warning に残し処理を継続する。
        """
        try:
            message = await channel.fetch_message(message_id)
            await message.unpin()
        except discord.DiscordException as e:
            logger.warning(
                "ピン解除に失敗しました (message_id=%s): %s", message_id, e
            )

    @staticmethod
    def mask_song_name(name: str) -> str:
        """
        楽曲名をマスクする

        例: "Magnolia" -> "********"
        空文字でも最低 1 文字の `"*"` を返し、embed タイトルが空になる事故を避ける。
        """
        if not name:
            return "*"
        return "*" * len(name)
