"""
session_manager.py のユニットテスト

`SessionManager` のシングルトン挙動とライフサイクル
(start / current / is_active / end / reset) に加え、
ステップ 5.1.1 で追加されたタイマー機構 (10 分前通知 / 30 分自動終了 用の
async コールバック発火・キャンセル) を検証します。

`pytest-asyncio` 等の追加依存を増やさないため、async 動作の検証は
`asyncio.run()` を呼ぶ同期テスト関数で完結させます (短い遅延秒を注入することで
コールバック発火順序やキャンセル挙動をリアルに観測する)。
"""

import asyncio
from datetime import datetime, timezone

import pytest

from src.services.session import Session
from src.services.session_manager import SessionManager
from tests.conftest import make_task


# ==================================================
# テスト用ヘルパー / fixture
# ==================================================
def _make_session(song_name: str = "Aragami") -> Session:
    """テスト用の最小 Session を組み立てる"""
    tasks = [make_task(type="level", set_value=1, value=5)]
    return Session(
        song_name=song_name,
        book="TestBook",
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
    `reset_singleton()` は内部で起動中タスクの `cancel()` も行うので、
    タイマーが残ったままテストが終わっても次のテストに影響しません。
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
    (タイマー機構を使わないケース。コールバック未指定なら従来通り即時登録のみ)
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
        kept = manager.current()
        assert kept is not None
        assert kept.song_name == "First"

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
        current = manager.current()
        assert current is not None
        assert current.song_name == "Second"

    def test_start_after_reset_succeeds(self):
        """
        reset() で解放した後は再び start() できる
        """
        manager = SessionManager.instance()
        manager.start(_make_session("First"))
        manager.reset()
        manager.start(_make_session("Second"))
        current = manager.current()
        assert current is not None
        assert current.song_name == "Second"


# ==================================================
# タイマー機構 (5.1.1)
# ==================================================
class TestTimers:
    """
    `start()` 経由で登録された on_warning / on_timeout の発火・キャンセル挙動

    検証は `asyncio.run()` 内の async ヘルパーで実施します。短い遅延秒を注入し、
    実際にイベントループ上でタスクが発火する/されないことを観測します。
    """

    # --------------------------------------------------
    # 正常系: 発火順序
    # --------------------------------------------------
    def test_warning_fires_before_timeout(self):
        """
        小さい遅延の方 (warning) が先に発火し、その後 timeout が発火する
        """

        async def scenario() -> list[str]:
            manager = SessionManager.instance()
            fired: list[str] = []

            async def on_warning() -> None:
                fired.append("warning")

            async def on_timeout() -> None:
                fired.append("timeout")
                manager.end()

            manager.start(
                _make_session(),
                on_warning=on_warning,
                on_timeout=on_timeout,
                warning_delay_seconds=0.02,
                timeout_delay_seconds=0.06,
            )

            # timeout が確実に発火するまで待つ (上限を設けハングを防ぐ)
            for _ in range(50):
                if "timeout" in fired:
                    break
                await asyncio.sleep(0.02)
            return fired

        fired = asyncio.run(scenario())
        assert fired == ["warning", "timeout"]

    def test_only_warning_callback_can_be_registered(self):
        """
        timeout 側のコールバックを与えなければ warning だけ発火する
        (片側だけの登録もサポート)
        """

        async def scenario() -> list[str]:
            manager = SessionManager.instance()
            fired: list[str] = []

            async def on_warning() -> None:
                fired.append("warning")

            manager.start(
                _make_session(),
                on_warning=on_warning,
                warning_delay_seconds=0.02,
            )

            # warning が発火するまで待つ
            for _ in range(50):
                if fired:
                    break
                await asyncio.sleep(0.02)
            manager.end()
            return fired

        assert asyncio.run(scenario()) == ["warning"]

    # --------------------------------------------------
    # 正常系: キャンセル
    # --------------------------------------------------
    def test_end_cancels_timers_before_firing(self):
        """
        end() を呼ぶと両タイマーがキャンセルされ、その後コールバックは発火しない
        """

        async def scenario() -> list[str]:
            manager = SessionManager.instance()
            fired: list[str] = []

            async def on_warning() -> None:
                fired.append("warning")

            async def on_timeout() -> None:
                fired.append("timeout")

            manager.start(
                _make_session(),
                on_warning=on_warning,
                on_timeout=on_timeout,
                warning_delay_seconds=0.05,
                timeout_delay_seconds=0.10,
            )
            # 発火前に終了
            manager.end()
            # 経過時間が遅延を超えても発火しないことを確認
            await asyncio.sleep(0.20)
            return fired

        assert asyncio.run(scenario()) == []

    def test_reset_cancels_timers_before_firing(self):
        """
        reset() でも両タイマーがキャンセルされる
        """

        async def scenario() -> list[str]:
            manager = SessionManager.instance()
            fired: list[str] = []

            async def on_warning() -> None:
                fired.append("warning")

            async def on_timeout() -> None:
                fired.append("timeout")

            manager.start(
                _make_session(),
                on_warning=on_warning,
                on_timeout=on_timeout,
                warning_delay_seconds=0.05,
                timeout_delay_seconds=0.10,
            )
            manager.reset()
            await asyncio.sleep(0.20)
            return fired

        assert asyncio.run(scenario()) == []

    def test_callback_not_invoked_after_end_called_between_warning_and_timeout(self):
        """
        warning 発火後・timeout 発火前に end() を呼べば、timeout は発火しない
        """

        async def scenario() -> list[str]:
            manager = SessionManager.instance()
            fired: list[str] = []
            warning_fired = asyncio.Event()

            async def on_warning() -> None:
                fired.append("warning")
                warning_fired.set()

            async def on_timeout() -> None:
                fired.append("timeout")

            manager.start(
                _make_session(),
                on_warning=on_warning,
                on_timeout=on_timeout,
                warning_delay_seconds=0.02,
                timeout_delay_seconds=0.20,
            )
            await asyncio.wait_for(warning_fired.wait(), timeout=1.0)
            manager.end()
            await asyncio.sleep(0.25)
            return fired

        assert asyncio.run(scenario()) == ["warning"]

    # --------------------------------------------------
    # 異常系: バリデーション
    # --------------------------------------------------
    def test_negative_warning_delay_raises(self):
        """
        負の warning_delay_seconds は ValueError
        """
        manager = SessionManager.instance()

        async def noop() -> None:
            return None

        with pytest.raises(ValueError, match="warning_delay_seconds"):
            manager.start(
                _make_session(),
                on_warning=noop,
                warning_delay_seconds=-1.0,
            )
        # 失敗時は登録されない
        assert manager.current() is None

    def test_negative_timeout_delay_raises(self):
        """
        負の timeout_delay_seconds は ValueError
        """
        manager = SessionManager.instance()

        async def noop() -> None:
            return None

        with pytest.raises(ValueError, match="timeout_delay_seconds"):
            manager.start(
                _make_session(),
                on_timeout=noop,
                timeout_delay_seconds=-0.5,
            )
        assert manager.current() is None

    def test_warning_must_be_less_than_timeout(self):
        """
        warning_delay_seconds >= timeout_delay_seconds は ValueError
        (10 分前通知が 30 分自動終了より後に来てしまう設定ミスを早期検出する)
        """
        manager = SessionManager.instance()

        async def noop() -> None:
            return None

        with pytest.raises(ValueError, match="warning_delay_seconds は"):
            manager.start(
                _make_session(),
                on_warning=noop,
                on_timeout=noop,
                warning_delay_seconds=10.0,
                timeout_delay_seconds=10.0,
            )
        assert manager.current() is None

    def test_callback_exception_is_logged_but_not_propagated(
        self, caplog: pytest.LogCaptureFixture
    ):
        """
        コールバックが例外を投げてもタイマー側で握って logger に出力する
        (要件「エラーは握りつぶさず、意味のあるメッセージ付きで処理する」に従い、
        例外を捨てずに traceback を残す)
        """
        import logging as _logging

        async def scenario() -> None:
            manager = SessionManager.instance()

            async def boom() -> None:
                raise RuntimeError("コールバック側のバグ")

            manager.start(
                _make_session(),
                on_warning=boom,
                warning_delay_seconds=0.02,
            )
            # warning タスクが発火し例外処理が完了するまで待つ
            assert manager._warning_task is not None
            await manager._warning_task
            manager.end()

        with caplog.at_level(_logging.ERROR, logger="src.services.session_manager"):
            asyncio.run(scenario())

        assert any(
            "セッションタイマー(warning)のコールバックで例外が発生しました"
            in rec.message
            for rec in caplog.records
        )

    def test_start_without_running_loop_raises_when_timer_requested(self):
        """
        コールバック+遅延を指定したのにイベントループが走っていない場合は
        `RuntimeError` を送出する (タイマーが起動できない状態を黙認しない)
        """
        manager = SessionManager.instance()

        async def noop() -> None:
            return None

        # 同期関数文脈ではイベントループが無い → asyncio.get_running_loop() が RuntimeError
        with pytest.raises(RuntimeError):
            manager.start(
                _make_session(),
                on_warning=noop,
                warning_delay_seconds=0.01,
            )
