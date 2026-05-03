"""
session_manager.py のユニットテスト

`SessionManager` のシングルトン挙動とライフサイクル
(start / current / is_active / end / reset) を検証します。
"""

from datetime import datetime, timezone

import pytest

from src.services.session import Session
from src.services.session_manager import SessionManager
from src.services.task import Task


# ==================================================
# テスト用ヘルパー / fixture
# ==================================================
def _make_session(song_name: str = "Aragami") -> Session:
    """テスト用の最小 Session を組み立てる"""
    tasks = [Task(type="level", set_value=1, value=5)]
    return Session(
        song_name=song_name,
        panel_count=1,
        tasks=tasks,
        channel_id=111,
        owner_id=222,
        started_at=datetime(2026, 5, 3, 10, 0, 0, tzinfo=timezone.utc),
    )


@pytest.fixture(autouse=True)
def reset_singleton():
    """
    各テスト前後で SessionManager のシングルトンキャッシュをクリアする

    別テストで生成された `_current` を引きずらないため必須。
    """
    SessionManager.reset_singleton()
    yield
    SessionManager.reset_singleton()


# ==================================================
# シングルトン
# ==================================================
class TestSingleton:
    """
    `SessionManager.instance()` の同一性
    """

    def test_instance_returns_same_object(self):
        """
        instance() は何度呼んでも同じインスタンスを返す
        """
        m1 = SessionManager.instance()
        m2 = SessionManager.instance()
        assert m1 is m2

    def test_reset_singleton_recreates_instance(self):
        """
        reset_singleton() 後の instance() は新しいインスタンスを返す
        """
        m1 = SessionManager.instance()
        SessionManager.reset_singleton()
        m2 = SessionManager.instance()
        assert m1 is not m2

    def test_reset_singleton_drops_current_session(self):
        """
        reset_singleton() で進行中セッションも消える
        """
        m1 = SessionManager.instance()
        m1.start(_make_session())
        SessionManager.reset_singleton()
        m2 = SessionManager.instance()
        assert m2.current() is None


# ==================================================
# ライフサイクル
# ==================================================
class TestLifecycle:
    """
    `start` / `current` / `is_active` / `end` / `reset` の振る舞い
    """

    def test_initial_state_is_inactive(self):
        """
        初期状態では現セッションは存在しない
        """
        manager = SessionManager.instance()
        assert manager.current() is None
        assert manager.is_active() is False

    def test_start_registers_session(self):
        """
        start() で current() にセッションが入り、is_active() が True になる
        """
        manager = SessionManager.instance()
        session = _make_session()
        manager.start(session)
        assert manager.current() is session
        assert manager.is_active() is True

    def test_start_rejects_double_start(self):
        """
        進行中セッションがある状態で start() を呼ぶと RuntimeError
        """
        manager = SessionManager.instance()
        manager.start(_make_session("First"))
        with pytest.raises(RuntimeError, match="既に進行中"):
            manager.start(_make_session("Second"))
        # 既存セッションは保持されたまま
        assert manager.current() is not None
        assert manager.current().song_name == "First"

    def test_end_returns_session_and_clears_state(self):
        """
        end() は終了対象を返し、内部状態をクリアする
        """
        manager = SessionManager.instance()
        session = _make_session()
        manager.start(session)
        ended = manager.end()
        assert ended is session
        assert manager.current() is None
        assert manager.is_active() is False

    def test_end_without_session_raises(self):
        """
        進行中セッションがない状態で end() を呼ぶと RuntimeError
        """
        manager = SessionManager.instance()
        with pytest.raises(RuntimeError, match="終了できる"):
            manager.end()

    def test_reset_clears_state(self):
        """
        reset() で進行中セッションを破棄できる
        """
        manager = SessionManager.instance()
        manager.start(_make_session())
        manager.reset()
        assert manager.current() is None
        assert manager.is_active() is False

    def test_reset_is_idempotent(self):
        """
        進行中セッションがなくても reset() は例外を投げない (冪等)
        """
        manager = SessionManager.instance()
        # 例外が発生しないこと
        manager.reset()
        manager.reset()
        assert manager.current() is None

    def test_start_after_end_succeeds(self):
        """
        end() で解放した後は再び start() できる
        """
        manager = SessionManager.instance()
        manager.start(_make_session("First"))
        manager.end()
        manager.start(_make_session("Second"))
        assert manager.current().song_name == "Second"

    def test_start_after_reset_succeeds(self):
        """
        reset() で解放した後は再び start() できる
        """
        manager = SessionManager.instance()
        manager.start(_make_session("First"))
        manager.reset()
        manager.start(_make_session("Second"))
        assert manager.current().song_name == "Second"
