"""
src/cogs/reset_session.py のユニットテスト

`/reset` コマンドの主な振る舞いを検証します:

* セッションが無い場合は ephemeral で通知応答し副作用を発生させない
* セッションがある場合は (defer →) ピン解除 → `SessionManager.reset()` の順で実行される
* `pinned_message_id` が None の場合はピン解除を試みない
* チャンネルが None / `fetch_message` 非対応でも reset 自体は実行される
* `discord.DiscordException` でピン解除が失敗しても reset は続行する
* `/reset` 完了後は `SessionManager.is_active()` が False に戻る
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from src.cogs.reset_session import ResetSessionCog
from src.services.session import Session
from src.services.session_manager import SessionManager
from tests.cogs.conftest import make_mock_interaction
from tests.conftest import make_task


# ==================================================
# 型検査回避ヘルパー
# ==================================================
def _invoke_reset(cog: ResetSessionCog, interaction: Any) -> Any:
    """`/reset` の素のコールバックを呼び出す薄いラッパ"""
    callback = cast(Any, cog.reset).callback
    return callback(cog, interaction)


# ==================================================
# 共通ヘルパー
# ==================================================
def _make_session(*, pinned_message_id: int | None = 42) -> Session:
    """SessionManager に登録するテスト用セッションを生成する"""
    return Session(
        song_name="Magnolia",
        panel_count=1,
        tasks=[make_task(type="level", set_value=1, value=5)],
        channel_id=2001,
        owner_id=1001,
        started_at=datetime(2026, 5, 7, tzinfo=timezone.utc),
        pinned_message_id=pinned_message_id,
    )


def _make_cog() -> ResetSessionCog:
    """テスト用 `ResetSessionCog` を生成する (依存無し)"""
    bot = MagicMock()
    return ResetSessionCog(bot=bot)


def _attach_pinned_message(interaction: Any) -> MagicMock:
    """
    `interaction.channel.fetch_message` がピン解除可能なメッセージ mock を返すよう差し替える

    Returns:
        ピン解除呼び出しを検証するためのメッセージ mock
    """
    pinned: MagicMock = MagicMock()
    pinned.unpin = AsyncMock()
    interaction.channel.fetch_message = AsyncMock(return_value=pinned)
    return pinned


# ==================================================
# fixture
# ==================================================
@pytest.fixture(autouse=True)
def reset_singleton():
    """各テスト前後で SessionManager をクリアする"""
    SessionManager.reset_singleton()
    yield
    SessionManager.reset_singleton()


# ==================================================
# セッション無し
# ==================================================
class TestResetWithoutActiveSession:
    """セッションが存在しないとき: ephemeral で通知し副作用を起こさない"""

    def test_responds_ephemeral_when_no_session(self):
        cog = _make_cog()
        interaction = make_mock_interaction()

        async def run() -> None:
            await _invoke_reset(cog, interaction)

        asyncio.run(run())

        # ephemeral で通知応答
        interaction.response.send_message.assert_awaited_once()
        _, kwargs = interaction.response.send_message.call_args
        assert kwargs.get("ephemeral") is True
        # defer / followup は呼ばれない (早期終了)
        interaction.response.defer.assert_not_called()
        interaction.followup.send.assert_not_called()
        # ピン解除も試みない
        interaction.channel.fetch_message.assert_not_called()
        # セッションは依然 None (no-op)
        assert SessionManager.instance().is_active() is False


# ==================================================
# セッション有り (Happy Path)
# ==================================================
class TestResetHappyPath:
    """進行中セッションがある場合: defer → ピン解除 → reset() → followup"""

    def test_unpins_and_resets(self):
        cog = _make_cog()
        session = _make_session(pinned_message_id=42)
        SessionManager.instance().start(session)

        interaction = make_mock_interaction()
        pinned = _attach_pinned_message(interaction)

        async def run() -> None:
            await _invoke_reset(cog, interaction)

        asyncio.run(run())

        # defer (ephemeral)
        interaction.response.defer.assert_awaited_once()
        defer_kwargs = interaction.response.defer.call_args.kwargs
        assert defer_kwargs.get("ephemeral") is True

        # ピン解除: fetch_message → unpin の順で呼ばれる
        interaction.channel.fetch_message.assert_awaited_once_with(42)
        pinned.unpin.assert_awaited_once()

        # SessionManager は reset() され空になっている
        assert SessionManager.instance().is_active() is False

        # followup で完了応答 (ephemeral)
        interaction.followup.send.assert_awaited_once()
        followup_kwargs = interaction.followup.send.call_args.kwargs
        assert followup_kwargs.get("ephemeral") is True

    def test_skips_unpin_when_no_pinned_message_id(self):
        """`pinned_message_id` が None ならピン解除は呼ばれない"""
        cog = _make_cog()
        session = _make_session(pinned_message_id=None)
        SessionManager.instance().start(session)

        interaction = make_mock_interaction()
        # fetch_message を AsyncMock として用意 (呼ばれないことを検証)
        interaction.channel.fetch_message = AsyncMock()

        async def run() -> None:
            await _invoke_reset(cog, interaction)

        asyncio.run(run())

        # defer はされる (成功パス)
        interaction.response.defer.assert_awaited_once()
        # ピン解除呼び出し無し
        interaction.channel.fetch_message.assert_not_called()
        # それでも reset() は実行されている
        assert SessionManager.instance().is_active() is False
        interaction.followup.send.assert_awaited_once()


# ==================================================
# 異常系: チャンネル None / fetch 非対応 / Discord 例外
# ==================================================
class TestResetUnpinFailureCases:
    """ピン解除が失敗・スキップされても `reset()` は実行される"""

    def test_resets_when_channel_missing(self, caplog):
        """`interaction.channel` が None でも reset は完了する"""
        cog = _make_cog()
        SessionManager.instance().start(_make_session(pinned_message_id=99))

        interaction = make_mock_interaction()
        interaction.channel = None

        with caplog.at_level(logging.WARNING, logger="src.cogs.reset_session"):

            async def run() -> None:
                await _invoke_reset(cog, interaction)

            asyncio.run(run())

        # warning ログにメッセージ ID が含まれる
        assert any("99" in rec.getMessage() for rec in caplog.records)
        # reset は実行されている
        assert SessionManager.instance().is_active() is False
        interaction.followup.send.assert_awaited_once()

    def test_resets_when_channel_not_messageable(self, caplog):
        """`Messageable` でないチャンネル (CategoryChannel 等) では warning + 続行"""
        cog = _make_cog()
        SessionManager.instance().start(_make_session(pinned_message_id=42))

        interaction = make_mock_interaction()
        # CategoryChannel は Messageable ではないため isinstance チェックで弾かれる
        interaction.channel = MagicMock(spec=discord.CategoryChannel)

        with caplog.at_level(logging.WARNING, logger="src.cogs.reset_session"):

            async def run() -> None:
                await _invoke_reset(cog, interaction)

            asyncio.run(run())

        # warning ログに message_id が含まれる (チャンネル取得不可と同じ経路)
        assert any("42" in rec.getMessage() for rec in caplog.records)
        assert SessionManager.instance().is_active() is False
        interaction.followup.send.assert_awaited_once()

    def test_resets_when_unpin_raises_discord_exception(self, caplog):
        """`fetch_message` / `unpin` が `DiscordException` を投げても reset は続行する"""
        cog = _make_cog()
        SessionManager.instance().start(_make_session(pinned_message_id=42))

        interaction = make_mock_interaction()
        interaction.channel.fetch_message = AsyncMock(
            side_effect=discord.DiscordException("boom")
        )

        with caplog.at_level(logging.WARNING, logger="src.cogs.reset_session"):

            async def run() -> None:
                await _invoke_reset(cog, interaction)

            asyncio.run(run())

        # ピン解除失敗の warning が記録される
        assert any(
            "ピン解除に失敗" in rec.getMessage() for rec in caplog.records
        )
        # それでも reset は完了している
        assert SessionManager.instance().is_active() is False
        interaction.followup.send.assert_awaited_once()
