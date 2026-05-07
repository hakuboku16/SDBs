"""
src/cogs/start_session.py のユニットテスト

`/start` コマンドの主な振る舞いを検証します。

* 引数バリデーション (許可されないパネル数 / 未知のモザイクラベル)
* 既存セッション存在時の拒否 (要件: 同時 1 セッションのみ)
* 成功パスでのメッセージ投稿・ピン留め・タイマー登録・`Session.pinned_message_id` 設定
* タイマー満了時の振る舞い (`on_warning` でチャンネル通知 / `on_timeout` で結果通知 + ピン解除 + 終了)

`discord.Interaction` は読み取り専用属性が多いため `tests/cogs/conftest.py` の
`make_mock_interaction` で擬似 Interaction を生成し、`interaction.followup.send` の
戻り値だけ送信済みメッセージ風 mock に差し替えています。
"""

import asyncio
import random
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Optional, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from discord import app_commands

from src.cogs.start_session import StartSessionCog
from src.core.config import DiscordConfig, SessionConfig
from src.services.session import Session
from src.services.session_manager import SessionManager
from src.services.song_repository import Song
from src.services.task import Task
from tests.cogs.conftest import make_mock_interaction


# ==================================================
# 型検査回避ヘルパー
# ==================================================
# `cog.start.callback` は app_commands.Command 経由で参照する素の async 関数で、
# pylance には `(interaction, ...)` の関数として推論されるため `(cog, interaction, ...)` の
# 呼び出しが型エラーになる。テストでは `cast(Any, ...)` で型検査を回避する。
def _invoke_start(
    cog: StartSessionCog, interaction: Any, **kwargs: Any
) -> Any:
    """`/start` の素のコールバックを呼び出す薄いラッパ"""
    callback = cast(Any, cog.start).callback
    return callback(cog, interaction, **kwargs)


def _bot_mock(cog: StartSessionCog) -> Any:
    """テストで cog.bot (MagicMock) を Any 経由で参照するためのアクセサ"""
    return cast(Any, cog.bot)


# ==================================================
# 共通ヘルパー
# ==================================================
def _sample_song(name: str = "SampleSong") -> Song:
    """テスト用の最小 Song を生成する"""
    return Song(
        name=name,
        shelf="A",
        book="B",
        version="v1",
        time=120,
        composer=["C"],
        levels={"Easy": 1},
        notes={"Easy": 100},
    )


def _sample_task(type_: str = "level") -> Task:
    """テスト用の最小 Task を生成する"""
    return Task(type=type_, set_value=1, value=5)


def _make_existing_session() -> Session:
    """`SessionManager` に注入する既存セッションを生成する"""
    return Session(
        song_name="ExistingSong",
        panel_count=1,
        tasks=[_sample_task()],
        channel_id=999,
        owner_id=888,
        started_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )


def _make_cog(
    *,
    songs: Optional[list[Song]] = None,
    tasks: Optional[list[Task]] = None,
    image_bytes: bytes = b"PNG_DATA",
    session_config: Optional[SessionConfig] = None,
    discord_config: Optional[DiscordConfig] = None,
) -> StartSessionCog:
    """
    全依存を mock 化した `StartSessionCog` を組み立てる

    bot.notifier は `notify_session_result` を `AsyncMock` で備えた擬似オブジェクト。
    `tasks` を明示しない場合、`gen.generate(panel_count)` の呼び出し引数に応じて
    適切な数の `Task` を返すよう side_effect で動的にリストを生成します
    (Session の panel_count == len(tasks) 検証を通すため)。
    """
    bot = MagicMock()
    bot.notifier = MagicMock()
    bot.notifier.notify_session_result = AsyncMock()

    repo = MagicMock()
    repo.all = MagicMock(return_value=songs if songs is not None else [_sample_song()])

    gen = MagicMock()
    if tasks is not None:
        gen.generate = MagicMock(return_value=tasks)
    else:
        gen.generate = MagicMock(
            side_effect=lambda panel_count: [
                _sample_task(f"t{i}") for i in range(panel_count)
            ]
        )

    proc = MagicMock()
    # compose は呼ばれるたびに新しい BytesIO を返す (discord.File が消費するため)
    proc.compose = MagicMock(side_effect=lambda **_: BytesIO(image_bytes))

    return StartSessionCog(
        bot=bot,
        song_repository=repo,
        task_generator=gen,
        image_processor=proc,
        session_config=session_config or SessionConfig(),
        discord_config=discord_config or DiscordConfig(),
        rng=random.Random(0),
    )


def _make_followup_message(message_id: int = 999_111_222) -> MagicMock:
    """ピン留め可能な `WebhookMessage` 風 mock を生成する"""
    msg = MagicMock()
    msg.id = message_id
    msg.pin = AsyncMock()
    msg.unpin = AsyncMock()
    return msg


def _attach_followup_message(interaction: MagicMock, message: MagicMock) -> None:
    """`interaction.followup.send` の戻り値を指定メッセージに差し替える"""
    interaction.followup.send = AsyncMock(return_value=message)


# ==================================================
# fixture
# ==================================================
@pytest.fixture(autouse=True)
def reset_singleton():
    """各テスト前後で SessionManager をクリア (タイマータスクも安全にキャンセル)"""
    SessionManager.reset_singleton()
    yield
    SessionManager.reset_singleton()


# ==================================================
# 既存セッション拒否
# ==================================================
class TestExistingSessionRejection:
    """既存セッションがある場合は ephemeral でエラー応答を返す"""

    def test_rejects_when_session_active(self):
        existing = _make_existing_session()
        SessionManager.instance().start(existing)

        cog = _make_cog()
        interaction = make_mock_interaction()

        async def run() -> None:
            await _invoke_start(cog, interaction)

        asyncio.run(run())

        # ephemeral でエラー応答
        interaction.response.send_message.assert_awaited_once()
        _, kwargs = interaction.response.send_message.call_args
        assert kwargs.get("ephemeral") is True

        # 既存セッションは保持され、別物に置き換わっていない
        manager = SessionManager.instance()
        assert manager.current() is existing

        # defer や followup は呼ばれない (早期終了)
        interaction.response.defer.assert_not_called()


# ==================================================
# 引数バリデーション
# ==================================================
class TestArgumentValidation:
    """`Choice` を介さず無効な値が渡されたケースのバリデーション"""

    def test_invalid_panel_count_rejected(self):
        # 9 のみ許可するカスタム設定で 4 を強制注入
        cfg = SessionConfig(default_panel_count=9, allowed_panel_counts=[9])
        cog = _make_cog(session_config=cfg)
        interaction = make_mock_interaction()
        choice_panels: app_commands.Choice[int] = app_commands.Choice(
            name="4", value=4
        )

        async def run() -> None:
            await _invoke_start(cog, interaction, panels=choice_panels)

        asyncio.run(run())

        interaction.response.send_message.assert_awaited_once()
        _, kwargs = interaction.response.send_message.call_args
        assert kwargs.get("ephemeral") is True
        # セッションは登録されない
        assert SessionManager.instance().current() is None

    def test_invalid_mosaic_label_rejected(self):
        # mosaic_levels に存在しないラベルを Choice で強制注入
        cog = _make_cog()
        interaction = make_mock_interaction()
        choice_mosaic: app_commands.Choice[str] = app_commands.Choice(
            name="ありえないラベル", value="ありえないラベル"
        )

        async def run() -> None:
            await _invoke_start(cog, interaction, mosaic=choice_mosaic)

        asyncio.run(run())

        interaction.response.send_message.assert_awaited_once()
        _, kwargs = interaction.response.send_message.call_args
        assert kwargs.get("ephemeral") is True
        assert SessionManager.instance().current() is None


# ==================================================
# 成功パス (Happy Path)
# ==================================================
class TestStartHappyPath:
    """正常系: メッセージ投稿 / ピン留め / セッション登録 / タイマー起動"""

    def test_session_registered_with_default_arguments(self):
        cog = _make_cog()
        interaction = make_mock_interaction()
        sent_message = _make_followup_message(message_id=12345)
        _attach_followup_message(interaction, sent_message)

        async def run() -> None:
            await _invoke_start(cog, interaction)
            # 同じ event loop 内でタイマー (asyncio.Task) を安全にキャンセル
            SessionManager.instance().reset()

        asyncio.run(run())

        # defer が呼ばれている (3 秒制限対応)
        interaction.response.defer.assert_awaited_once()
        # メッセージが送信されている
        interaction.followup.send.assert_awaited_once()

    def test_pinned_message_id_recorded(self):
        cog = _make_cog()
        interaction = make_mock_interaction()
        sent_message = _make_followup_message(message_id=555_666_777)
        _attach_followup_message(interaction, sent_message)

        captured: dict[str, Optional[Session]] = {"session": None}

        async def run() -> None:
            await _invoke_start(cog, interaction)
            captured["session"] = SessionManager.instance().current()
            SessionManager.instance().reset()

        asyncio.run(run())

        sent_message.pin.assert_awaited_once()
        session = captured["session"]
        assert session is not None
        assert session.pinned_message_id == 555_666_777

    def test_pin_failure_is_logged_but_does_not_abort(self):
        """ピン留め失敗時も投稿自体は成功させ、セッションは登録される"""
        cog = _make_cog()
        interaction = make_mock_interaction()
        sent_message = _make_followup_message()
        # discord.DiscordException を継承する例外を pin で発生させる
        import discord as _discord

        sent_message.pin = AsyncMock(side_effect=_discord.Forbidden(MagicMock(), "no perm"))
        _attach_followup_message(interaction, sent_message)

        async def run() -> None:
            await _invoke_start(cog, interaction)
            SessionManager.instance().reset()

        # 例外が伝播しない
        asyncio.run(run())
        # メッセージは投稿されている
        interaction.followup.send.assert_awaited_once()

    def test_callbacks_registered_with_delays_from_config(self):
        """
        SessionManager.start に on_warning / on_timeout と
        config から計算された遅延秒が渡される
        """
        # 元の SessionManager.start を spy してキャプチャする
        manager = SessionManager.instance()
        original_start = manager.start
        captured: dict[str, object] = {}

        def spy_start(session, **kwargs):
            captured["session"] = session
            captured.update(kwargs)
            return original_start(session, **kwargs)

        manager.start = spy_start  # type: ignore[assignment]

        cog = _make_cog()
        interaction = make_mock_interaction()
        sent_message = _make_followup_message()
        _attach_followup_message(interaction, sent_message)

        async def run() -> None:
            await _invoke_start(cog, interaction)
            SessionManager.instance().reset()

        asyncio.run(run())

        # コールバックが両方登録されている
        assert "on_warning" in captured and captured["on_warning"] is not None
        assert "on_timeout" in captured and captured["on_timeout"] is not None
        # 遅延秒は config から計算 (default: warning=10 分, timeout=30 分)
        # warning_delay_seconds = (30 - 10) * 60 = 1200
        # timeout_delay_seconds = 30 * 60 = 1800
        assert captured["warning_delay_seconds"] == 1200.0
        assert captured["timeout_delay_seconds"] == 1800.0

    def test_panels_argument_overrides_default(self):
        """panels 引数で指定した値が Session.panel_count に反映される"""
        # 16 パネル分のタスクを返すよう gen を設定
        cog = _make_cog(tasks=[_sample_task(f"t{i}") for i in range(16)])
        interaction = make_mock_interaction()
        sent_message = _make_followup_message()
        _attach_followup_message(interaction, sent_message)
        choice = app_commands.Choice(name="16", value=16)

        captured: dict[str, Optional[Session]] = {"session": None}

        async def run() -> None:
            await _invoke_start(cog, interaction, panels=choice)
            captured["session"] = SessionManager.instance().current()
            SessionManager.instance().reset()

        asyncio.run(run())

        session = captured["session"]
        assert session is not None
        assert session.panel_count == 16

    def test_mosaic_argument_overrides_default(self):
        """mosaic 引数で指定したラベルから block 値が解決される"""
        cog = _make_cog()
        interaction = make_mock_interaction()
        sent_message = _make_followup_message()
        _attach_followup_message(interaction, sent_message)
        # SessionConfig 既定で "強" は 45px
        choice = app_commands.Choice(name="強", value="強")

        captured: dict[str, Optional[Session]] = {"session": None}

        async def run() -> None:
            await _invoke_start(cog, interaction, mosaic=choice)
            captured["session"] = SessionManager.instance().current()
            SessionManager.instance().reset()

        asyncio.run(run())

        session = captured["session"]
        assert session is not None
        assert session.mosaic_block == 45


# ==================================================
# 内部ヘルパー (_finalize_session 委譲 / _notify_warning)
# ==================================================
class TestFinalizeSession:
    """`on_timeout` 経由で呼ばれる内部処理の単体検証 (`SessionFinalizer` への委譲)"""

    def test_finalize_invokes_notifier_and_unpin_and_end(self):
        """
        finalize は (1) 結果通知、(2) ピン解除、(3) SessionManager.end の順に実行する。
        実処理は `SessionFinalizer.finalize` 経由で行われる。
        """
        cog = _make_cog()
        # 既存セッションを SessionManager に登録 (タイマー無し)
        session = _make_existing_session()
        session.pinned_message_id = 42_42_42
        SessionManager.instance().start(session)

        # チャンネル mock: fetch_message でピン付メッセージを返し、unpin を AsyncMock に
        pinned_msg = MagicMock()
        pinned_msg.unpin = AsyncMock()
        channel = MagicMock()
        channel.fetch_message = AsyncMock(return_value=pinned_msg)

        async def run() -> None:
            await cog._finalize_session(session, channel)

        asyncio.run(run())

        # 1) 結果通知が呼ばれた (時間切れの summary 付き)
        _bot_mock(cog).notifier.notify_session_result.assert_awaited_once()
        kwargs = _bot_mock(cog).notifier.notify_session_result.await_args.kwargs
        assert kwargs["summary"] == "セッション終了 (時間切れ)"
        assert kwargs["masked_song_name"] == "*" * len(session.song_name)
        # 2) ピン解除が呼ばれた
        channel.fetch_message.assert_awaited_once_with(42_42_42)
        pinned_msg.unpin.assert_awaited_once()
        # 3) セッションが破棄された
        assert SessionManager.instance().is_active() is False

    def test_finalize_is_noop_when_no_active_session(self):
        """二重終了防止: 既に終了済みなら何もしない"""
        cog = _make_cog()
        session = _make_existing_session()
        # SessionManager に登録しない (= is_active() == False)
        channel = MagicMock()

        async def run() -> None:
            await cog._finalize_session(session, channel)

        asyncio.run(run())

        _bot_mock(cog).notifier.notify_session_result.assert_not_called()
        channel.fetch_message.assert_not_called()


class TestNotifyWarning:
    """`on_warning` 経由で呼ばれる残り時間警告"""

    def test_sends_warning_to_channel(self):
        cog = _make_cog()
        channel = MagicMock()
        channel.send = AsyncMock()

        async def run() -> None:
            await cog._notify_warning(channel)

        asyncio.run(run())

        channel.send.assert_awaited_once()
        # 警告分数 (config 既定: 10 分) が文字列に含まれる
        args, _ = channel.send.call_args
        assert "10" in args[0]

    def test_send_failure_is_logged_but_does_not_raise(self):
        """送信失敗時もハンドラ全体を巻き込まない"""
        import discord as _discord

        cog = _make_cog()
        channel = MagicMock()
        channel.send = AsyncMock(
            side_effect=_discord.HTTPException(MagicMock(), "boom")
        )

        async def run() -> None:
            await cog._notify_warning(channel)

        # 例外が伝播しない
        asyncio.run(run())
        channel.send.assert_awaited_once()
