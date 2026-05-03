"""
SDBsBot のユニットテスト

`SDBsBot` は `commands.Bot` を継承するため、実コネクションを張らずに
振る舞いを検証する必要があります。本テストでは:

- `commands.Bot.__init__` を mock し、Bot 初期化に伴う Gateway 接続準備を回避
- `setup_hook` 内で呼ばれる `load_extension` / `tree.sync` / `tree.copy_global_to` を
  AsyncMock / MagicMock で差し替え、引数を検証
- `on_app_command_error` は `discord.Interaction` のモックに対して
  `notifier.notify_error` と ephemeral 応答が呼ばれることを検証
"""

import asyncio
from contextlib import contextmanager
from typing import Iterator
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import discord
import pytest
from discord import app_commands
from discord.ext import commands

from src.core.bot import SDBsBot
from src.core.config import DiscordConfig


# ==================================================
# 共通ヘルパー
# ==================================================
def _make_config(command_sync_guilds: list[int] | None = None) -> DiscordConfig:
    """
    テスト用の DiscordConfig を組み立てる
    """
    return DiscordConfig(
        command_sync_guilds=command_sync_guilds if command_sync_guilds is not None else [],
        log_channel_id=100,
        result_channel_id=200,
    )


def _build_bot_without_super_init() -> SDBsBot:
    """
    `commands.Bot.__init__` を skip して `SDBsBot` を生成する

    discord.py の `commands.Bot` は内部で接続準備や HTTPClient 初期化を行うため
    本物の `__init__` を通すとテストが重く・不安定になります。`__init__` を mock し
    `SDBsBot.__init__` 側で行う属性設定 (config / notifier) のみ実行させます。
    """
    with patch.object(commands.Bot, "__init__", return_value=None):
        return SDBsBot(_make_config())


@contextmanager
def _patch_tree() -> Iterator[MagicMock]:
    """
    `SDBsBot.tree` は `commands.Bot` 由来の read-only property のため、
    インスタンス側ではなくクラス側に `PropertyMock` をパッチして mock に差し替える

    Yields:
        差し込んだ tree のモック (sync / copy_global_to をテストから検証可能にする)
    """
    tree_mock = MagicMock()
    tree_mock.sync = AsyncMock()
    tree_mock.copy_global_to = MagicMock()
    with patch.object(SDBsBot, "tree", new_callable=PropertyMock) as prop:
        prop.return_value = tree_mock
        yield tree_mock


def _run(coro) -> None:
    """asyncio.run の薄いラッパ"""
    asyncio.run(coro)


# ==================================================
# __init__
# ==================================================
class TestInit:
    """`__init__` の振る舞い"""

    def test_stores_config_and_initial_notifier_is_none(self):
        """config を保持し、notifier は setup_hook 前は None"""
        bot = _build_bot_without_super_init()
        assert isinstance(bot.config, DiscordConfig)
        assert bot.notifier is None

    def test_super_init_called_with_intents_and_dummy_prefix(self):
        """`commands.Bot.__init__` にダミー prefix と intents が渡る"""
        with patch.object(commands.Bot, "__init__", return_value=None) as mock_super_init:
            SDBsBot(_make_config())

        mock_super_init.assert_called_once()
        kwargs = mock_super_init.call_args.kwargs
        assert "command_prefix" in kwargs
        assert kwargs["command_prefix"] == SDBsBot._DUMMY_PREFIX
        assert isinstance(kwargs["intents"], discord.Intents)
        # スラッシュコマンドのみで運用するため help_command は無効化
        assert kwargs.get("help_command") is None

    def test_uses_provided_intents(self):
        """intents 引数が指定されればそれが使われる"""
        custom_intents = discord.Intents.none()
        with patch.object(commands.Bot, "__init__", return_value=None) as mock_super_init:
            SDBsBot(_make_config(), intents=custom_intents)

        kwargs = mock_super_init.call_args.kwargs
        assert kwargs["intents"] is custom_intents


# ==================================================
# setup_hook: cog 自動ロード
# ==================================================
class TestSetupHookLoadCogs:
    """`setup_hook` が cog を自動ロードする"""

    @pytest.fixture
    def fake_iter_modules(self) -> Iterator[MagicMock]:
        """
        `pkgutil.iter_modules` を制御するための fixture

        2 つのモジュール (start_session, end_session) と 1 つのサブパッケージを返し、
        サブパッケージはスキップされること、モジュールはロードされることを検証する。
        """
        with patch("src.core.bot.pkgutil.iter_modules") as mock_iter:
            mock_iter.return_value = [
                MagicMock(name="start_session", ispkg=False),
                MagicMock(name="end_session", ispkg=False),
                MagicMock(name="some_subpackage", ispkg=True),
            ]
            # MagicMock の name 属性は特別扱いされるため明示的に設定する
            mock_iter.return_value[0].name = "start_session"
            mock_iter.return_value[1].name = "end_session"
            mock_iter.return_value[2].name = "some_subpackage"
            yield mock_iter

    def test_loads_each_module_via_load_extension(self, fake_iter_modules):
        """全モジュールを `load_extension("src.cogs.<name>")` でロードする"""
        bot = _build_bot_without_super_init()
        bot.load_extension = AsyncMock()

        with _patch_tree():
            _run(bot.setup_hook())

        loaded = [call.args[0] for call in bot.load_extension.await_args_list]
        assert "src.cogs.start_session" in loaded
        assert "src.cogs.end_session" in loaded
        # サブパッケージはスキップされる
        assert "src.cogs.some_subpackage" not in loaded

    def test_continues_when_one_extension_fails(self, fake_iter_modules):
        """1 つの cog のロードが失敗しても残りの cog のロードは継続する"""
        bot = _build_bot_without_super_init()

        async def fake_load(name: str) -> None:
            if name == "src.cogs.start_session":
                raise commands.ExtensionFailed(name, RuntimeError("boom"))

        bot.load_extension = AsyncMock(side_effect=fake_load)

        with _patch_tree():
            # 例外で Bot 起動全体が止まらないことを確認
            _run(bot.setup_hook())

        loaded = [call.args[0] for call in bot.load_extension.await_args_list]
        assert "src.cogs.start_session" in loaded
        assert "src.cogs.end_session" in loaded

    def test_initializes_notifier_in_setup_hook(self, fake_iter_modules):
        """setup_hook 完了後 self.notifier が DiscordNotifier として有効になる"""
        bot = _build_bot_without_super_init()
        bot.load_extension = AsyncMock()

        assert bot.notifier is None
        with _patch_tree():
            _run(bot.setup_hook())
        # DiscordNotifier の具体型を import すると循環するためメソッドの存在で確認
        assert bot.notifier is not None
        assert hasattr(bot.notifier, "notify_error")
        assert hasattr(bot.notifier, "notify_session_result")

    def test_skips_load_when_cog_package_import_fails(
        self, caplog: pytest.LogCaptureFixture
    ):
        """cog パッケージの import に失敗した場合は warning を残しロードをスキップする"""
        import logging as _logging

        bot = _build_bot_without_super_init()
        bot.load_extension = AsyncMock()

        with _patch_tree(), patch(
            "src.core.bot.importlib.import_module",
            side_effect=ImportError("not found"),
        ), caplog.at_level(_logging.WARNING, logger="src.core.bot"):
            _run(bot.setup_hook())

        bot.load_extension.assert_not_awaited()
        assert any(
            "cog パッケージを import できませんでした" in rec.message
            for rec in caplog.records
        )

    def test_skips_load_when_package_has_no_path(
        self, caplog: pytest.LogCaptureFixture
    ):
        """import 結果に `__path__` がなければ warning を残してロードをスキップする"""
        import logging as _logging

        bot = _build_bot_without_super_init()
        bot.load_extension = AsyncMock()

        # `__path__` が存在しない仮モジュールを返させる
        fake_module = MagicMock(spec=[])
        with _patch_tree(), patch(
            "src.core.bot.importlib.import_module", return_value=fake_module
        ), caplog.at_level(_logging.WARNING, logger="src.core.bot"):
            _run(bot.setup_hook())

        bot.load_extension.assert_not_awaited()
        assert any(
            "パッケージではないため cog 自動ロードをスキップ" in rec.message
            for rec in caplog.records
        )


# ==================================================
# setup_hook: コマンド同期
# ==================================================
class TestSetupHookSyncCommands:
    """`setup_hook` がコマンドツリーを同期する"""

    @pytest.fixture(autouse=True)
    def patch_iter_modules(self):
        """各テストで cog 列挙を空にしてロード処理を無効化"""
        with patch("src.core.bot.pkgutil.iter_modules", return_value=[]):
            yield

    def test_syncs_globally_when_guild_list_is_empty(self):
        """`command_sync_guilds` が空ならグローバル同期する"""
        with patch.object(commands.Bot, "__init__", return_value=None):
            bot = SDBsBot(_make_config(command_sync_guilds=[]))
        bot.load_extension = AsyncMock()

        with _patch_tree() as tree:
            _run(bot.setup_hook())

            # グローバル同期は guild 引数なしで sync が呼ばれる
            tree.sync.assert_awaited_once_with()
            tree.copy_global_to.assert_not_called()

    def test_syncs_to_each_guild_when_specified(self):
        """`command_sync_guilds` が指定されると各 Guild に同期する"""
        with patch.object(commands.Bot, "__init__", return_value=None):
            bot = SDBsBot(_make_config(command_sync_guilds=[111, 222]))
        bot.load_extension = AsyncMock()

        with _patch_tree() as tree:
            _run(bot.setup_hook())

            # 各 Guild に対して copy_global_to → sync が呼ばれる
            copy_calls = tree.copy_global_to.call_args_list
            sync_calls = tree.sync.await_args_list
            assert len(copy_calls) == 2
            assert len(sync_calls) == 2

            copied_ids = sorted(c.kwargs["guild"].id for c in copy_calls)
            synced_ids = sorted(c.kwargs["guild"].id for c in sync_calls)
            assert copied_ids == [111, 222]
            assert synced_ids == [111, 222]


# ==================================================
# on_app_command_error
# ==================================================
class TestOnAppCommandError:
    """`on_app_command_error` の振る舞い"""

    def _make_interaction(self, *, response_done: bool) -> MagicMock:
        """
        ephemeral 応答ルートを切り替えるための Interaction モック

        Args:
            response_done: response.is_done() の戻り値 (defer 等で応答済みなら True)
        """
        interaction = MagicMock(spec=discord.Interaction)
        interaction.command = MagicMock()
        interaction.command.qualified_name = "start"

        interaction.response = MagicMock()
        interaction.response.is_done = MagicMock(return_value=response_done)
        interaction.response.send_message = AsyncMock()

        interaction.followup = MagicMock()
        interaction.followup.send = AsyncMock()

        return interaction

    def test_notifies_log_channel_with_traceback(self):
        """notifier.notify_error が呼ばれ、コマンド名と例外が渡される"""
        bot = _build_bot_without_super_init()
        bot.notifier = MagicMock()
        bot.notifier.notify_error = AsyncMock()

        interaction = self._make_interaction(response_done=False)
        error = app_commands.AppCommandError("テストエラー")

        _run(bot.on_app_command_error(interaction, error))

        bot.notifier.notify_error.assert_awaited_once()
        args, kwargs = bot.notifier.notify_error.await_args
        # 第 1 引数 (位置/キーワードどちらでも) にコマンド名が含まれる
        message_arg = args[0] if args else kwargs.get("message")
        assert "/start" in message_arg
        # exc は AppCommandError そのもの
        assert kwargs.get("exc") is error

    def test_responds_ephemerally_when_not_yet_responded(self):
        """response.is_done が False なら response.send_message が呼ばれる"""
        bot = _build_bot_without_super_init()
        bot.notifier = MagicMock()
        bot.notifier.notify_error = AsyncMock()

        interaction = self._make_interaction(response_done=False)
        _run(bot.on_app_command_error(interaction, app_commands.AppCommandError("x")))

        interaction.response.send_message.assert_awaited_once()
        kwargs = interaction.response.send_message.await_args.kwargs
        assert kwargs.get("ephemeral") is True
        interaction.followup.send.assert_not_awaited()

    def test_responds_via_followup_when_already_responded(self):
        """response.is_done が True なら followup.send が呼ばれる"""
        bot = _build_bot_without_super_init()
        bot.notifier = MagicMock()
        bot.notifier.notify_error = AsyncMock()

        interaction = self._make_interaction(response_done=True)
        _run(bot.on_app_command_error(interaction, app_commands.AppCommandError("x")))

        interaction.followup.send.assert_awaited_once()
        kwargs = interaction.followup.send.await_args.kwargs
        assert kwargs.get("ephemeral") is True
        interaction.response.send_message.assert_not_awaited()

    def test_swallows_followup_failure(self):
        """ユーザーへの応答が失敗しても例外が伝播しない"""
        bot = _build_bot_without_super_init()
        bot.notifier = MagicMock()
        bot.notifier.notify_error = AsyncMock()

        interaction = self._make_interaction(response_done=True)
        interaction.followup.send = AsyncMock(
            side_effect=discord.DiscordException("応答失敗")
        )

        # 例外が漏れないことが本テストの主眼
        _run(bot.on_app_command_error(interaction, app_commands.AppCommandError("x")))

        bot.notifier.notify_error.assert_awaited_once()

    def test_logs_error_when_notifier_is_none(self, caplog: pytest.LogCaptureFixture):
        """notifier 未初期化でも応答処理は走り、logger にエラーが残る"""
        import logging as _logging

        bot = _build_bot_without_super_init()
        bot.notifier = None

        interaction = self._make_interaction(response_done=False)

        with caplog.at_level(_logging.ERROR, logger="src.core.bot"):
            _run(bot.on_app_command_error(interaction, app_commands.AppCommandError("x")))

        assert any("notifier 未初期化" in rec.message for rec in caplog.records)
        # ユーザーへの応答は走る
        interaction.response.send_message.assert_awaited_once()

    def test_swallows_notifier_failure(self, caplog: pytest.LogCaptureFixture):
        """notifier への通知が DiscordException を投げてもユーザー応答は実行される"""
        import logging as _logging

        bot = _build_bot_without_super_init()
        bot.notifier = MagicMock()
        bot.notifier.notify_error = AsyncMock(
            side_effect=discord.DiscordException("通知失敗")
        )

        interaction = self._make_interaction(response_done=False)

        with caplog.at_level(_logging.WARNING, logger="src.core.bot"):
            _run(bot.on_app_command_error(interaction, app_commands.AppCommandError("x")))

        # ログチャンネル通知の失敗は warning に残る
        assert any(
            "ログチャンネルへの通知に失敗" in rec.message for rec in caplog.records
        )
        # それでもユーザー応答は走る (二次障害でブロックしないこと)
        interaction.response.send_message.assert_awaited_once()
