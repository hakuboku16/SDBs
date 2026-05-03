"""
Discord チャンネルへの通知を担うモジュール

`DiscordNotifier` はログチャンネル / 結果チャンネルへの送信窓口を提供する薄いラッパです。
通知用チャンネル ID 未設定や送信失敗時はサイレントに握りつぶさず、必ずロガーに warning を残します
(要件「エラーは握りつぶさず、意味のあるメッセージ付きで処理する」)。
"""

import logging
import traceback
from io import BytesIO
from typing import Optional

import discord

from src.core.config import DiscordConfig

# モジュールスコープのロガー。`setup_logger("__main__")` 経由の親ロガーから
# propagate されることを想定 (production)。テストでは pytest の caplog で捕捉する。
logger = logging.getLogger(__name__)


# ==================================================
# DiscordNotifier
# ==================================================
class DiscordNotifier:
    """
    Discord 上の指定チャンネルへ通知を送るラッパ

    - エラー通知 → `DiscordConfig.log_channel_id`
    - セッション結果通知 → `DiscordConfig.result_channel_id`

    いずれもチャンネル ID 未設定時は warning を出して送信をスキップします。
    """

    # Discord メッセージ本文の最大長 (公式仕様: 2000 文字)
    _MAX_CONTENT_LENGTH: int = 2000

    # 結果画像の Discord 添付ファイル名
    _RESULT_IMAGE_FILENAME: str = "session_result.png"

    # 切り詰めた際に挿入するマーカー (先頭に付与し、末尾を残す)
    _TRUNCATE_MARKER: str = "…(切り詰め)…\n"

    def __init__(self, client: discord.Client, config: DiscordConfig) -> None:
        """
        通知ラッパを初期化する

        Args:
            client: Bot のクライアント (チャンネル取得・送信に使用)
            config: Discord 設定 (送信先チャンネル ID を含む)
        """
        self._client: discord.Client = client
        self._log_channel_id: Optional[int] = config.log_channel_id
        self._result_channel_id: Optional[int] = config.result_channel_id

    # --------------------------------------------------
    # 公開 API
    # --------------------------------------------------
    async def notify_error(
        self,
        message: str,
        exc: Optional[BaseException] = None,
    ) -> None:
        """
        エラーをログチャンネルへ通知する

        例外オブジェクトが指定された場合は traceback を整形してメッセージに付加します。
        Discord 制限 (2000 文字) を超える場合は先頭を切り詰めて末尾 (例外の発生箇所側) を残します。

        Args:
            message: エラー概要 (発生箇所やユーザー操作の文脈など)
            exc: 例外オブジェクト。None の場合は概要メッセージのみ送信
        """
        content: str = message
        if exc is not None:
            tb_text: str = "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            )
            # コードブロックで囲み traceback を可読化
            content = f"{message}\n```\n{tb_text}```"

        await self._send(
            channel_id=self._log_channel_id,
            channel_label="ログ",
            content=self._truncate(content),
        )

    async def notify_session_result(
        self,
        image: BytesIO,
        masked_song_name: str,
        summary: str,
    ) -> None:
        """
        セッション終了時の結果を結果チャンネルへ通知する

        Args:
            image: 現状の合成画像 (PNG, シーク位置は呼び出し側で先頭にしておく)
            masked_song_name: マスク済みの楽曲名 (例: "***")
            summary: 集計結果テキスト (回答ログなど)
        """
        content: str = self._truncate(f"楽曲: {masked_song_name}\n{summary}")
        # discord.File はラップ対象の BytesIO を消費するため毎回新規にラップする
        file: discord.File = discord.File(image, filename=self._RESULT_IMAGE_FILENAME)
        await self._send(
            channel_id=self._result_channel_id,
            channel_label="結果",
            content=content,
            file=file,
        )

    # --------------------------------------------------
    # 内部ヘルパー
    # --------------------------------------------------
    async def _send(
        self,
        channel_id: Optional[int],
        channel_label: str,
        content: str,
        file: Optional[discord.File] = None,
    ) -> None:
        """
        指定チャンネルへ送信する。失敗時は握りつぶさずロガーに warning を残す。

        Args:
            channel_id: 送信先のチャンネル ID。None の場合は warning を出してスキップ
            channel_label: ログメッセージ用の人間可読な種別名 ("ログ" / "結果")
            content: 送信本文 (空文字でも可)
            file: 添付ファイル (省略可)
        """
        if channel_id is None:
            logger.warning(
                "%sチャンネル ID が未設定のため送信をスキップします (head=%r)",
                channel_label,
                content[:100],
            )
            return

        channel = self._client.get_channel(channel_id)
        if channel is None:
            logger.warning(
                "%sチャンネル (id=%s) を取得できませんでした。Bot がチャンネルを認識していない可能性があります。",
                channel_label,
                channel_id,
            )
            return

        # `send` を持たない型 (例: カテゴリ) は通知不能
        send = getattr(channel, "send", None)
        if not callable(send):
            logger.warning(
                "%sチャンネル (id=%s, type=%s) は send をサポートしていません。",
                channel_label,
                channel_id,
                type(channel).__name__,
            )
            return

        try:
            if file is not None:
                await send(content=content, file=file)
            else:
                await send(content=content)
        except discord.DiscordException as e:
            # Discord 由来のエラーのみ握り、ロガーに残す。それ以外は呼び出し側に伝播させる。
            logger.warning(
                "%sチャンネル (id=%s) への送信に失敗しました: %s",
                channel_label,
                channel_id,
                e,
            )

    @classmethod
    def _truncate(cls, content: str) -> str:
        """
        Discord の 2000 文字制限に収まるよう先頭を切り詰める

        traceback の場合、底 (例外発生箇所) が末尾にあるため末尾を残す方が情報量が多い。

        Args:
            content: 切り詰め前のメッセージ本文

        Returns:
            切り詰め後の本文 (元から短い場合はそのまま)
        """
        if len(content) <= cls._MAX_CONTENT_LENGTH:
            return content
        keep: int = cls._MAX_CONTENT_LENGTH - len(cls._TRUNCATE_MARKER)
        return cls._TRUNCATE_MARKER + content[-keep:]
