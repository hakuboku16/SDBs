"""
src/cogs/end_session.py のユニットテスト

`/end` コマンドの主な振る舞いを検証します:

* セッションが無い場合は ephemeral でエラー応答 (defer しない / finalizer 不呼び出し)
* セッションがある場合は ``SessionFinalizer.finalize`` に
  ``summary="セッション終了"`` で委譲され、defer + 完了 followup が走ること
* `bot.notifier` が finalizer に引き渡されること
* チャンネル無しケースの早期エラー応答

`SessionFinalizer` 自体の挙動 (embed 構成 / ピン解除 / SessionManager.end 順序) は
[tests/services/test_session_finalizer.py](tests/services/test_session_finalizer.py)
で検証済みのため、本 cog テストでは委譲呼び出しのみを確認します。
"""

import asyncio
from datetime import datetime, timezone
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.cogs.end_session import EndSessionCog
from src.services.session import Session
from src.services.session_manager import SessionManager
from tests.cogs.conftest import make_mock_interaction
from tests.conftest import make_task


# ==================================================
# 型検査回避ヘルパー
# ==================================================
def _invoke_end(cog: EndSessionCog, interaction: Any) -> Any:
    """`/end` の素のコールバックを呼び出す薄いラッパ"""
    callback = cast(Any, cog.end).callback
    return callback(cog, interaction)


def _bot_mock(cog: EndSessionCog) -> Any:
    """テストで cog.bot (MagicMock) を Any 経由で参照するためのアクセサ"""
    return cast(Any, cog.bot)


# ==================================================
# 共通ヘルパー
# ==================================================
def _make_session() -> Session:
    """SessionManager に登録するテスト用セッションを生成する"""
    return Session(
        song_name="Magnolia",
        panel_count=1,
        tasks=[make_task(type="level", set_value=1, value=5)],
        channel_id=2001,
        owner_id=1001,
        started_at=datetime(2026, 5, 7, tzinfo=timezone.utc),
        pinned_message_id=42,
    )


def _make_cog(*, finalizer: MagicMock | None = None) -> EndSessionCog:
    """全依存を mock 化した `EndSessionCog` を組み立てる"""
    bot = MagicMock()
    bot.notifier = MagicMock()
    bot.notifier.notify_session_result = AsyncMock()

    if finalizer is None:
        finalizer = MagicMock()
        finalizer.finalize = AsyncMock()

    return EndSessionCog(bot=bot, session_finalizer=finalizer)


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
# セッション無し
# ==================================================
class TestEndWithoutActiveSession:
    """セッションが存在しないとき: ephemeral でエラー応答し finalizer は呼ばれない"""

    def test_responds_ephemeral_when_no_session(self):
        cog = _make_cog()
        interaction = make_mock_interaction()

        async def run() -> None:
            await _invoke_end(cog, interaction)

        asyncio.run(run())

        # ephemeral でエラー応答
        interaction.response.send_message.assert_awaited_once()
        _, kwargs = interaction.response.send_message.call_args
        assert kwargs.get("ephemeral") is True
        # defer / followup は呼ばれない (早期終了)
        interaction.response.defer.assert_not_called()
        interaction.followup.send.assert_not_called()
        # finalizer も呼ばれない
        cast(Any, cog._session_finalizer).finalize.assert_not_called()


# ==================================================
# セッション有り (Happy Path)
# ==================================================
class TestEndHappyPath:
    """進行中セッションがある場合: defer → finalizer 委譲 → followup"""

    def test_delegates_to_finalizer_with_summary(self):
        cog = _make_cog()
        # 既存セッションを SessionManager に登録 (タイマー無し)
        session = _make_session()
        SessionManager.instance().start(session)

        interaction = make_mock_interaction()

        async def run() -> None:
            await _invoke_end(cog, interaction)

        asyncio.run(run())

        # defer (ephemeral) されている
        interaction.response.defer.assert_awaited_once()
        defer_kwargs = interaction.response.defer.call_args.kwargs
        assert defer_kwargs.get("ephemeral") is True

        # finalizer.finalize が呼ばれた
        finalize_mock = cast(Any, cog._session_finalizer).finalize
        finalize_mock.assert_awaited_once()
        args, kwargs = finalize_mock.call_args
        # 第 1 引数: session
        assert args[0] is session
        # 第 2 引数: interaction.channel
        assert args[1] is interaction.channel
        # 第 3 引数: bot.notifier
        assert args[2] is _bot_mock(cog).notifier
        # summary は "セッション終了"
        assert kwargs["summary"] == "セッション終了"

        # 完了応答が ephemeral でユーザーへ届く (embed 形式)
        interaction.followup.send.assert_awaited_once()
        followup_kwargs = interaction.followup.send.call_args.kwargs
        assert followup_kwargs.get("ephemeral") is True
        # embed として送られ、楽曲名が description に含まれる
        embed = followup_kwargs.get("embed")
        import discord as _discord
        assert isinstance(embed, _discord.Embed)
        assert embed.description is not None
        assert "Magnolia" in embed.description

    def test_passes_none_notifier_when_bot_has_no_notifier(self):
        """`bot.notifier` 未設定なら ``None`` を finalizer に渡す"""
        cog = _make_cog()
        # bot から notifier 属性を消す (getattr default = None)
        del _bot_mock(cog).notifier

        SessionManager.instance().start(_make_session())
        interaction = make_mock_interaction()

        async def run() -> None:
            await _invoke_end(cog, interaction)

        asyncio.run(run())

        finalize_mock = cast(Any, cog._session_finalizer).finalize
        finalize_mock.assert_awaited_once()
        args, _ = finalize_mock.call_args
        assert args[2] is None


# ==================================================
# チャンネル無し
# ==================================================
class TestEndWithoutChannel:
    """`interaction.channel` が None のケース"""

    def test_responds_ephemeral_when_channel_missing(self):
        cog = _make_cog()
        SessionManager.instance().start(_make_session())

        interaction = make_mock_interaction()
        interaction.channel = None

        async def run() -> None:
            await _invoke_end(cog, interaction)

        asyncio.run(run())

        interaction.response.send_message.assert_awaited_once()
        _, kwargs = interaction.response.send_message.call_args
        assert kwargs.get("ephemeral") is True
        # finalizer は呼ばれない
        cast(Any, cog._session_finalizer).finalize.assert_not_called()
        # SessionManager は依然 active (この経路では破棄しない)
        assert SessionManager.instance().is_active() is True
