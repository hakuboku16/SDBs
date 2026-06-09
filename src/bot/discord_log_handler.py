from __future__ import annotations

import asyncio
import logging


def should_forward(record: logging.LogRecord, threshold: int) -> bool:
    """ログレコードを Discord ログチャンネルへ転送すべきか判定する。

    Args:
        record: 判定対象のログレコード。
        threshold: 転送する最小レベル(これ以上を転送する)。

    Returns:
        bool: threshold 以上の重大度で、かつ discord ライブラリ由来でなければ True。
    """
    # discord.* 由来を転送するとログch送信がさらにログを生み無限ループになるため除外する。
    if record.name.startswith("discord"):
        return False
    return record.levelno >= threshold


class DiscordLogHandler(logging.Handler):
    """WARNING 以上のログを asyncio キュー経由でログチャンネルへ送る Handler。

    emit はイベントループ外スレッドからも呼ばれ得るため、ここではキュー投入のみを
    call_soon_threadsafe で行い、実送信はループ上の消費タスクへ委ねる。
    """

    def __init__(
        self,
        queue: asyncio.Queue[str],
        loop: asyncio.AbstractEventLoop,
        level: int = logging.WARNING,
    ) -> None:
        """送信キューとイベントループを保持して初期化する。

        Args:
            queue: 整形済みログ文字列を渡す送信キュー。
            loop: キュー投入をスケジュールするイベントループ。
            level: 転送する最小ログレベル。
        """
        super().__init__(level)
        self._queue = queue
        self._loop = loop

    def emit(self, record: logging.LogRecord) -> None:
        """転送対象なら整形してキューへ投入する。

        Args:
            record: 出力対象のログレコード。
        """
        if not should_forward(record, self.level):
            return
        message = self.format(record)
        # ループ停止後にログが出ても呼び出し元へ例外を伝播させず Handler 規約どおり処理する。
        try:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, message)
        except Exception:
            self.handleError(record)
