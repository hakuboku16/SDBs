"""
Discord チャンネルへの通知を担うモジュール

`DiscordNotifier` はログチャンネル / 結果チャンネルへの送信窓口を提供する薄いラッパです。
通知用チャンネル ID 未設定や送信失敗時はサイレントに握りつぶさず、必ずロガーに warning を残します
(要件「エラーは握りつぶさず、意味のあるメッセージ付きで処理する」)。
"""

import logging
import traceback
from io import BytesIO
from typing import Any, Iterable, Optional, cast

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

    # Discord embed.description の最大長 (公式仕様: 4096 文字)
    _MAX_DESCRIPTION_LENGTH: int = 4096

    # Discord embed field 値の最大長 (公式仕様: 1024 文字)
    _MAX_FIELD_LENGTH: int = 1024

    # 結果画像の Discord 添付ファイル名
    _RESULT_IMAGE_FILENAME: str = "session_result.png"

    # 切り詰めた際に挿入するマーカー (先頭に付与し、末尾を残す)
    _TRUNCATE_MARKER: str = "…(切り詰め)…\n"

    # エラー通知 embed のタイトル / 色 (Bot から送るメッセージは embed 統一の方針)
    _ERROR_EMBED_TITLE: str = "エラー"
    _ERROR_EMBED_COLOR: discord.Color = discord.Color.red()

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
        Bot からの送信は embed 形式に統一されているため、embed.description にメッセージと
        コードブロックを格納します。Discord embed.description 制限 (4096 文字) を超える
        場合は先頭を切り詰めて末尾 (例外の発生箇所側) を残します。

        Args:
            message: エラー概要 (発生箇所やユーザー操作の文脈など)
            exc: 例外オブジェクト。None の場合は概要メッセージのみ送信
        """
        description: str = message
        if exc is not None:
            tb_text: str = "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            )
            # コードブロックで囲み traceback を可読化
            description = f"{message}\n```\n{tb_text}```"

        embed: discord.Embed = discord.Embed(
            title=self._ERROR_EMBED_TITLE,
            description=self._truncate(description),
            color=self._ERROR_EMBED_COLOR,
        )
        await self._send(
            channel_id=self._log_channel_id,
            channel_label="ログ",
            content="",
            embed=embed,
        )

    # 結果通知 embed の固定タイトル (楽曲名は description にスポイラーで載せるため)
    _RESULT_EMBED_TITLE: str = "🎵 セッション結果"

    async def notify_session_result(
        self,
        image: BytesIO,
        spoiler_song_name: str,
        correct_answerers: Iterable[tuple[int, str]],
        summary: Optional[str] = None,
    ) -> None:
        """
        セッション終了時の結果を結果チャンネルへ embed で通知する

        embed 構成:
            - title: 固定文言 ("🎵 セッション結果")
            - description: 任意の補足テキスト + 楽曲名 (スポイラー)。
              embed.title はスポイラー記法を描画しないため、楽曲名は description に出す。
            - image: 現状の合成パネル画像
            - field "正解者": ``correct_answerers`` のユーザー名一覧。
              0 件の場合は「正解者なし」を表示する。

        Args:
            image: 現状の合成画像 (PNG, シーク位置は呼び出し側で先頭にしておく)
            spoiler_song_name: スポイラー記法で包んだ楽曲名 (例: "||Magnolia            ||")
            correct_answerers: 正解者の ``(user_id, user_name)`` の反復子。
                ``set`` 由来の場合は反復順が不定なため、内部で ``user_name`` 昇順に
                ソートしてから表示する。
            summary: embed description に出す補足文。``None`` なら省略する。
        """
        # 反復順は呼び出し側 (set など) で不定の可能性があるため、表示安定化のため名前で昇順ソート
        answerer_list: list[tuple[int, str]] = sorted(
            correct_answerers, key=lambda pair: pair[1]
        )

        song_line: str = f"楽曲名: {spoiler_song_name}"
        description: str = (
            f"{summary}\n{song_line}" if summary is not None else song_line
        )
        embed: discord.Embed = discord.Embed(
            title=self._RESULT_EMBED_TITLE,
            description=description,
        )
        # 添付ファイルを embed の画像として参照する (attachment スキーム)
        embed.set_image(url=f"attachment://{self._RESULT_IMAGE_FILENAME}")

        if answerer_list:
            answerer_text: str = "\n".join(
                f"- {user_name}" for _, user_name in answerer_list
            )
        else:
            answerer_text = "正解者なし"
        # Discord field の値は 1024 文字制限があるため切り詰める
        embed.add_field(
            name="正解者",
            value=self._truncate_field(answerer_text),
            inline=False,
        )

        # discord.File はラップ対象の BytesIO を消費するため毎回新規にラップする
        file: discord.File = discord.File(image, filename=self._RESULT_IMAGE_FILENAME)
        await self._send(
            channel_id=self._result_channel_id,
            channel_label="結果",
            content="",
            file=file,
            embed=embed,
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
        embed: Optional[discord.Embed] = None,
    ) -> None:
        """
        指定チャンネルへ送信する。失敗時は握りつぶさずロガーに warning を残す。

        Args:
            channel_id: 送信先のチャンネル ID。None の場合は warning を出してスキップ
            channel_label: ログメッセージ用の人間可読な種別名 ("ログ" / "結果")
            content: 送信本文 (空文字でも可)
            file: 添付ファイル (省略可)
            embed: 送信する embed (省略可)
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
        send_attr = getattr(channel, "send", None)
        if not callable(send_attr):
            logger.warning(
                "%sチャンネル (id=%s, type=%s) は send をサポートしていません。",
                channel_label,
                channel_id,
                type(channel).__name__,
            )
            return
        # `getattr` の戻り値は object 型として推論され `await` の型推論が通らないため
        # ここで `Any` にキャストして discord.py の awaitable シグネチャに追従させる
        send = cast(Any, send_attr)

        try:
            # discord.py の send は省略時に sentinel が想定されているため、
            # 実際に渡す組み合わせを分岐して呼ぶ (None を直接渡さない)
            if file is not None and embed is not None:
                await send(content=content, file=file, embed=embed)
            elif file is not None:
                await send(content=content, file=file)
            elif embed is not None:
                await send(content=content, embed=embed)
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
        Discord embed.description の 4096 文字制限に収まるよう先頭を切り詰める

        traceback の場合、底 (例外発生箇所) が末尾にあるため末尾を残す方が情報量が多い。

        Args:
            content: 切り詰め前のメッセージ本文

        Returns:
            切り詰め後の本文 (元から短い場合はそのまま)
        """
        if len(content) <= cls._MAX_DESCRIPTION_LENGTH:
            return content
        keep: int = cls._MAX_DESCRIPTION_LENGTH - len(cls._TRUNCATE_MARKER)
        return cls._TRUNCATE_MARKER + content[-keep:]

    @classmethod
    def _truncate_field(cls, value: str) -> str:
        """
        Discord embed field 値の 1024 文字制限に収まるよう末尾を切り詰める

        正解者リストでは先頭側 (アルファベット昇順の早い名前) を残した方が表示の
        一貫性が保てるため、末尾側を切り詰める。

        Args:
            value: 切り詰め前の field 値

        Returns:
            切り詰め後の値 (元から短い場合はそのまま)
        """
        if len(value) <= cls._MAX_FIELD_LENGTH:
            return value
        keep: int = cls._MAX_FIELD_LENGTH - len(cls._TRUNCATE_MARKER)
        return value[:keep] + cls._TRUNCATE_MARKER
