"""
セッションのライフサイクル管理を担うモジュール

`SessionManager` はシングルトンとして単一の `Session` を保持し、
「同時に存在できるセッションは 1 つだけ」という要件を保証します。

ステップ 5.1.1 で 30 分自動終了 / 10 分前通知のタイマー機構を追加しました。
タイマーは `asyncio.Task` として `start()` 内で起動し、`end()` / `reset()` で
キャンセルされます。コールバック自体は Discord 依存処理 (チャンネル投稿など) を
担うため cog 層から注入する設計とし、本モジュール自体は Discord に依存しません。
"""

import asyncio
import logging
from typing import Awaitable, Callable, Optional

from src.services.session import Session


# モジュールスコープのロガー (production では `__main__` 親ロガーから propagate)
logger = logging.getLogger(__name__)

# タイマー満了時に呼び出される async コールバックの型エイリアス
SessionCallback = Callable[[], Awaitable[None]]


# ==================================================
# SessionManager
# ==================================================
class SessionManager:
    """
    プロセス全体で唯一の `Session` を保持するシングルトン

    インスタンス変数 `_current` に現セッションを保持し、`start()` 時に既存セッションが
    あれば `RuntimeError` を送出して同時 1 セッション制約を担保します。

    タイマー機構 (10 分前通知 / 30 分自動終了) も本クラスが担います。`start()` で
    遅延秒とコールバックを受け取り `asyncio.create_task` で 2 本のタスクを起動、
    `end()` / `reset()` で両タスクをキャンセルします。

    本クラスはインメモリのみを取り扱うため、Bot 再起動でセッションは消失します
    (要件で許容)。
    """

    # クラス変数: シングルトンインスタンス本体
    _instance: Optional["SessionManager"] = None

    def __init__(self) -> None:
        """
        コンストラクタ

        通常は `instance()` から取得してください。複数回インスタンス化しても
        各インスタンスは独立したセッションを保持しますが、`instance()` 経由なら
        プロセス全体で同一インスタンスが返ります。
        """
        self._current: Optional[Session] = None
        # タイマー機構の状態
        self._warning_task: Optional[asyncio.Task[None]] = None
        self._timeout_task: Optional[asyncio.Task[None]] = None

    # --------------------------------------------------
    # シングルトン取得・リセット
    # --------------------------------------------------
    @classmethod
    def instance(cls) -> "SessionManager":
        """
        プロセス全体で共有されるシングルトンインスタンスを返す
        """
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_singleton(cls) -> None:
        """
        シングルトンキャッシュを破棄する (主にテスト用)

        既存インスタンスが保持していた現セッションも破棄され、起動中のタイマー
        タスクも安全にキャンセルされます。
        """
        if cls._instance is not None:
            cls._instance._cancel_timers()
        cls._instance = None

    # --------------------------------------------------
    # セッション操作
    # --------------------------------------------------
    def start(
        self,
        session: Session,
        *,
        on_warning: Optional[SessionCallback] = None,
        on_timeout: Optional[SessionCallback] = None,
        warning_delay_seconds: Optional[float] = None,
        timeout_delay_seconds: Optional[float] = None,
    ) -> None:
        """
        新規セッションを登録し、必要に応じてタイマーを起動する

        Args:
            session: 登録する `Session` オブジェクト
            on_warning: 残り時間警告 (10 分前通知) 用 async コールバック
            on_timeout: セッション制限時間到達時の async コールバック
            warning_delay_seconds: `on_warning` を発火するまでの秒数
                (None またはコールバック未指定なら警告タスクを起動しない)
            timeout_delay_seconds: `on_timeout` を発火するまでの秒数
                (None またはコールバック未指定なら自動終了タスクを起動しない)

        Raises:
            RuntimeError: 既に進行中のセッションが存在する場合
                (要件: 同時 1 セッションのみ)
            ValueError: 遅延秒が負値の場合、または警告 >= 自動終了 の場合
            RuntimeError: タイマー起動が要求されたのにイベントループが走っていない場合
        """
        if self._current is not None:
            raise RuntimeError(
                "既に進行中のセッションが存在します。/end または /reset で終了してから再度開始してください。"
            )

        # 遅延値のバリデーション (Discord 設定上の数値ミスや短秒数注入時の事故を防ぐ)
        self._validate_delay("warning_delay_seconds", warning_delay_seconds)
        self._validate_delay("timeout_delay_seconds", timeout_delay_seconds)
        if (
            warning_delay_seconds is not None
            and timeout_delay_seconds is not None
            and warning_delay_seconds >= timeout_delay_seconds
        ):
            raise ValueError(
                "warning_delay_seconds は timeout_delay_seconds より小さい必要があります "
                f"(warning={warning_delay_seconds}, timeout={timeout_delay_seconds})"
            )

        self._current = session

        # コールバックと遅延が両方与えられた場合のみタイマーを起動する
        if on_warning is not None and warning_delay_seconds is not None:
            self._warning_task = self._schedule(
                warning_delay_seconds, on_warning, "warning"
            )
        if on_timeout is not None and timeout_delay_seconds is not None:
            self._timeout_task = self._schedule(
                timeout_delay_seconds, on_timeout, "timeout"
            )

    def current(self) -> Optional[Session]:
        """
        現セッションを返す (なければ None)
        """
        return self._current

    def is_active(self) -> bool:
        """
        進行中のセッションがあるかを返す
        """
        return self._current is not None

    def end(self) -> Session:
        """
        現セッションを正常終了させ、対象オブジェクトを返す

        `/end` および 30 分タイマー満了で呼ばれることを想定し、終了時に
        セッション内容を参照したい呼び出し側 (結果集計など) に渡せるよう
        終了対象を返します。タイマータスクが残っていれば併せてキャンセルします。

        Returns:
            終了した `Session`

        Raises:
            RuntimeError: 進行中のセッションが存在しない場合
        """
        if self._current is None:
            raise RuntimeError("終了できるセッションが存在しません。")
        ended = self._current
        self._current = None
        self._cancel_timers()
        return ended

    def reset(self) -> None:
        """
        現セッションを破棄する (進行中でなくてもエラーにならない)

        `/reset` から呼ばれることを想定し、強制クリア用途として例外を送出しません。
        タイマータスクが残っていれば併せてキャンセルします。
        """
        self._current = None
        self._cancel_timers()

    # --------------------------------------------------
    # タイマー内部処理
    # --------------------------------------------------
    @staticmethod
    def _validate_delay(name: str, value: Optional[float]) -> None:
        """
        遅延秒の妥当性を検証する (None は許容、負値は ValueError)
        """
        if value is None:
            return
        if value < 0:
            raise ValueError(f"{name} は 0 以上の値を指定してください: {value}")

    @classmethod
    def _schedule(
        cls,
        delay_seconds: float,
        callback: SessionCallback,
        label: str,
    ) -> "asyncio.Task[None]":
        """
        遅延発火コルーチンを `asyncio.Task` として登録する

        `asyncio.get_running_loop()` 経由でタスク化することで、イベントループが
        走っていない状況では `RuntimeError` を即座に送出します
        (タイマーが起動できない状態を黙って受け入れない)。
        """
        loop = asyncio.get_running_loop()
        return loop.create_task(cls._run_after(delay_seconds, callback, label))

    @staticmethod
    async def _run_after(
        delay_seconds: float,
        callback: SessionCallback,
        label: str,
    ) -> None:
        """
        指定秒スリープ後に `callback` を呼び出すラッパ

        - `CancelledError` は伝播させ、`end()` / `reset()` でのキャンセルが
          正常終了として扱われるようにする
        - その他の例外は logger に出力する (ここで握ると要件「エラーは握りつぶさない」に
          反するため、内容を必ず記録する)
        """
        try:
            await asyncio.sleep(delay_seconds)
            await callback()
        except asyncio.CancelledError:
            # end()/reset() による正常キャンセル
            raise
        except Exception:
            logger.exception(
                "セッションタイマー(%s)のコールバックで例外が発生しました", label
            )

    def _cancel_timers(self) -> None:
        """
        起動中の警告/自動終了タスクを安全にキャンセルしクリアする

        既に完了済みのタスクは触らず、未完了のものだけ `cancel()` を呼びます。
        参照は必ず None に戻し、次回 `start()` 時の状態リークを防ぎます。
        """
        for task in (self._warning_task, self._timeout_task):
            if task is not None and not task.done():
                task.cancel()
        self._warning_task = None
        self._timeout_task = None
