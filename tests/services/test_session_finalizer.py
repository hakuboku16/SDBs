"""
session_finalizer.py のユニットテスト

`SessionFinalizer.finalize` の以下の振る舞いを検証します:

* 結果通知 → ピン解除 → SessionManager.end の順で実行されること
* セッションが既に非アクティブなら全処理が no-op (二重終了防止)
* 画像合成失敗時は通知をスキップしつつピン解除・セッション破棄は継続すること
* `pinned_message_id` が None の場合はピン解除を試みないこと
* notifier 未初期化 (`None`) の場合は警告ログを残し通知をスキップすること
* `format_spoiler_song_name` の単体挙動
"""

import asyncio
import logging
from datetime import datetime, timezone
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from src.services.session import Session
from src.services.session_finalizer import SessionFinalizer
from src.services.session_manager import SessionManager
from src.services.task import Task
from tests.conftest import make_task


# ==================================================
# 共通ヘルパー
# ==================================================
def _make_task() -> Task:
    """副作用のないシンプルな Task"""
    return make_task(type="level", set_value=1, value=5)


def _make_session(*, pinned_message_id: int | None = 12345) -> Session:
    """テスト用 Session を生成する"""
    session = Session(
        song_name="Magnolia",
        book="Deemo Original",
        panel_count=1,
        tasks=[_make_task()],
        channel_id=999,
        owner_id=888,
        started_at=datetime(2026, 5, 7, tzinfo=timezone.utc),
    )
    session.pinned_message_id = pinned_message_id
    return session


def _make_image_processor(*, image_bytes: bytes = b"PNG") -> MagicMock:
    """compose が常に新しい BytesIO を返す ImageProcessor mock"""
    proc = MagicMock()
    proc.compose = MagicMock(side_effect=lambda **_: BytesIO(image_bytes))
    return proc


def _make_notifier() -> MagicMock:
    """notify_session_result を AsyncMock として備えた notifier mock"""
    notifier = MagicMock()
    notifier.notify_session_result = AsyncMock()
    return notifier


def _make_channel_with_pinned_message() -> tuple[MagicMock, MagicMock]:
    """
    fetch_message → unpin の経路を備えた擬似チャンネルを返す

    Returns:
        (channel mock, pinned message mock) のタプル
    """
    pinned = MagicMock()
    pinned.unpin = AsyncMock()
    channel = MagicMock()
    channel.fetch_message = AsyncMock(return_value=pinned)
    return channel, pinned


def _run(coro) -> None:
    asyncio.run(coro)


# ==================================================
# fixture
# ==================================================
@pytest.fixture(autouse=True)
def reset_singleton():
    """各テスト前後で SessionManager をクリア"""
    SessionManager.reset_singleton()
    yield
    SessionManager.reset_singleton()


# ==================================================
# format_spoiler_song_name
# ==================================================
class TestFormatSpoilerSongName:
    """`format_spoiler_song_name` の振る舞い"""

    def test_includes_book_in_spoiler(self):
        """楽曲名と book 名をスポイラーで包む"""
        result = SessionFinalizer.format_spoiler_song_name("Magnolia", "Deemo Original")
        assert result == "||Magnolia (Deemo Original)||"

    def test_works_with_long_name(self):
        """長い楽曲名でも切り詰めずそのまま包む"""
        long_name = "A" * 30
        result = SessionFinalizer.format_spoiler_song_name(long_name, "SomeBook")
        assert result == f"||{long_name} (SomeBook)||"

    def test_spoiler_markers_present(self):
        """先頭と末尾に || が付く"""
        result = SessionFinalizer.format_spoiler_song_name("ANiMA", "Book1")
        assert result.startswith("||") and result.endswith("||")


# ==================================================
# finalize: 正常系
# ==================================================
class TestFinalizeHappyPath:
    """`finalize` の主要シーケンスを検証する"""

    def test_invokes_notify_unpin_and_end_in_order(self):
        proc = _make_image_processor()
        finalizer = SessionFinalizer(image_processor=proc)
        session = _make_session(pinned_message_id=42)
        SessionManager.instance().start(session)

        notifier = _make_notifier()
        channel, pinned = _make_channel_with_pinned_message()

        _run(
            finalizer.finalize(
                session, channel, notifier, summary="セッション終了"
            )
        )

        # 1) 結果通知が呼ばれる
        notifier.notify_session_result.assert_awaited_once()
        kwargs = notifier.notify_session_result.await_args.kwargs
        # 楽曲名は book 名と合わせてスポイラー記法で包まれて渡る
        assert kwargs["spoiler_song_name"] == "||Magnolia (Deemo Original)||"
        # 正解者は session の set がそのまま渡る
        assert kwargs["correct_answerers"] == session.correct_answerers
        assert kwargs["summary"] == "セッション終了"

        # 2) ピン解除が呼ばれる
        channel.fetch_message.assert_awaited_once_with(42)
        pinned.unpin.assert_awaited_once()

        # 3) セッションが破棄される
        assert SessionManager.instance().is_active() is False

    def test_compose_receives_session_rotation_angle(self):
        """
        終了時の最終画像合成では、`compose` に `Session.rotation_angle` がそのまま渡る。

        Why: セッション開始時に決定した角度を結果通知でも再利用しないと、結果チャン
        ネルに送る画像とセッション中ユーザーが見ていた画像で向きが食い違う (本リグ
        レッションテスト)。
        """
        proc = _make_image_processor()
        finalizer = SessionFinalizer(image_processor=proc)
        session = _make_session()
        session.rotate = True
        session.rotation_angle = 270
        SessionManager.instance().start(session)

        notifier = _make_notifier()
        channel, _ = _make_channel_with_pinned_message()

        _run(finalizer.finalize(session, channel, notifier))

        proc.compose.assert_called_once()
        compose_kwargs = proc.compose.call_args.kwargs
        assert compose_kwargs["rotation_angle"] == 270

    def test_passes_correct_answerers_from_session(self):
        """`Session.correct_answerers` がそのまま notifier に渡される"""
        proc = _make_image_processor()
        finalizer = SessionFinalizer(image_processor=proc)
        session = _make_session()
        session.add_correct_answerer(1, "alice")
        session.add_correct_answerer(2, "bob")
        SessionManager.instance().start(session)

        notifier = _make_notifier()
        channel, _ = _make_channel_with_pinned_message()

        _run(finalizer.finalize(session, channel, notifier))

        kwargs = notifier.notify_session_result.await_args.kwargs
        assert kwargs["correct_answerers"] == {(1, "alice"), (2, "bob")}


# ==================================================
# finalize: 二重終了防止
# ==================================================
class TestFinalizeNoOp:
    """既に非アクティブな場合は全処理が no-op"""

    def test_does_nothing_when_session_inactive(self):
        proc = _make_image_processor()
        finalizer = SessionFinalizer(image_processor=proc)
        # SessionManager に登録しない (= is_active() == False)
        session = _make_session()

        notifier = _make_notifier()
        channel, _ = _make_channel_with_pinned_message()

        _run(finalizer.finalize(session, channel, notifier))

        notifier.notify_session_result.assert_not_called()
        channel.fetch_message.assert_not_called()
        proc.compose.assert_not_called()


# ==================================================
# finalize: 画像合成失敗
# ==================================================
class TestFinalizeImageCompositionFailure:
    """画像合成失敗時の振る舞い"""

    def test_skips_notify_but_unpins_and_ends_when_compose_raises(
        self, caplog: pytest.LogCaptureFixture
    ):
        """
        compose が ValueError 等を投げた場合、通知はスキップしつつ
        ピン解除と SessionManager.end は実行する
        """
        proc = MagicMock()
        proc.compose = MagicMock(side_effect=ValueError("不正なパラメータ"))
        finalizer = SessionFinalizer(image_processor=proc)
        session = _make_session(pinned_message_id=42)
        SessionManager.instance().start(session)

        notifier = _make_notifier()
        channel, pinned = _make_channel_with_pinned_message()

        with caplog.at_level(
            logging.WARNING, logger="src.services.session_finalizer"
        ):
            _run(finalizer.finalize(session, channel, notifier))

        # 通知はスキップされる
        notifier.notify_session_result.assert_not_called()
        # warning は残っている
        assert any("画像合成に失敗" in rec.message for rec in caplog.records)
        # ピン解除は実行される
        pinned.unpin.assert_awaited_once()
        # セッション破棄も実行される
        assert SessionManager.instance().is_active() is False


# ==================================================
# finalize: ピン留め関連
# ==================================================
class TestFinalizeUnpin:
    """ピン解除の枝分かれ"""

    def test_skips_unpin_when_pinned_message_id_none(self):
        """`pinned_message_id` が None ならピン解除処理を行わない"""
        proc = _make_image_processor()
        finalizer = SessionFinalizer(image_processor=proc)
        session = _make_session(pinned_message_id=None)
        SessionManager.instance().start(session)

        notifier = _make_notifier()
        channel, _ = _make_channel_with_pinned_message()

        _run(finalizer.finalize(session, channel, notifier))

        channel.fetch_message.assert_not_called()
        # 通知とセッション破棄は通常通り実行される
        notifier.notify_session_result.assert_awaited_once()
        assert SessionManager.instance().is_active() is False

    def test_logs_warning_when_unpin_raises_discord_exception(
        self, caplog: pytest.LogCaptureFixture
    ):
        """unpin が DiscordException を投げても全体は止めず warning を残す"""
        proc = _make_image_processor()
        finalizer = SessionFinalizer(image_processor=proc)
        session = _make_session(pinned_message_id=42)
        SessionManager.instance().start(session)

        notifier = _make_notifier()
        pinned = MagicMock()
        pinned.unpin = AsyncMock(
            side_effect=discord.HTTPException(MagicMock(), "boom")
        )
        channel = MagicMock()
        channel.fetch_message = AsyncMock(return_value=pinned)

        with caplog.at_level(
            logging.WARNING, logger="src.services.session_finalizer"
        ):
            _run(finalizer.finalize(session, channel, notifier))

        assert any("ピン解除に失敗" in rec.message for rec in caplog.records)
        # 後続のセッション破棄は完了する
        assert SessionManager.instance().is_active() is False


# ==================================================
# finalize: notifier 未初期化
# ==================================================
class TestFinalizeNotifierMissing:
    """`notifier` が None のケース"""

    def test_logs_warning_when_notifier_is_none(
        self, caplog: pytest.LogCaptureFixture
    ):
        proc = _make_image_processor()
        finalizer = SessionFinalizer(image_processor=proc)
        session = _make_session()
        SessionManager.instance().start(session)

        channel, pinned = _make_channel_with_pinned_message()

        with caplog.at_level(
            logging.WARNING, logger="src.services.session_finalizer"
        ):
            _run(finalizer.finalize(session, channel, None))

        assert any(
            "DiscordNotifier 未初期化" in rec.message for rec in caplog.records
        )
        # ピン解除とセッション破棄は通常通り行われる
        pinned.unpin.assert_awaited_once()
        assert SessionManager.instance().is_active() is False
