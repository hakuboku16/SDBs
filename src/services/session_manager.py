"""
セッションのライフサイクル管理を担うモジュール

`SessionManager` はシングルトンとして単一の `Session` を保持し、
「同時に存在できるセッションは 1 つだけ」という要件を保証します。

タイマー処理 (10 分前通知 / 30 分自動終了) は Discord 依存があるため
ステップ 4 以降の Bot 層に持ち、本モジュールではセッションオブジェクトの
登録・取得・解放のみを扱います。
"""

from typing import Optional

from src.services.session import Session


# ==================================================
# SessionManager
# ==================================================
class SessionManager:
    """
    プロセス全体で唯一の `Session` を保持するシングルトン

    インスタンス変数 `_current` に現セッションを保持し、`start()` 時に既存セッションが
    あれば `RuntimeError` を送出して同時 1 セッション制約を担保します。

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

        既存インスタンスが保持していた現セッションも破棄されます。
        """
        cls._instance = None

    # --------------------------------------------------
    # セッション操作
    # --------------------------------------------------
    def start(self, session: Session) -> None:
        """
        新規セッションを登録する

        Args:
            session: 登録する `Session` オブジェクト

        Raises:
            RuntimeError: 既に進行中のセッションが存在する場合
                (要件: 同時 1 セッションのみ)
        """
        if self._current is not None:
            raise RuntimeError(
                "既に進行中のセッションが存在します。/end または /reset で終了してから再度開始してください。"
            )
        self._current = session

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
        終了対象を返します。

        Returns:
            終了した `Session`

        Raises:
            RuntimeError: 進行中のセッションが存在しない場合
        """
        if self._current is None:
            raise RuntimeError("終了できるセッションが存在しません。")
        ended = self._current
        self._current = None
        return ended

    def reset(self) -> None:
        """
        現セッションを破棄する (進行中でなくてもエラーにならない)

        `/reset` から呼ばれることを想定し、強制クリア用途として例外を送出しません。
        """
        self._current = None
