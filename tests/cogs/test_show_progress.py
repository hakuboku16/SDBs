"""
src/cogs/show_progress.py のユニットテスト

`/progress` コマンドの主な振る舞いを検証します:

* セッションが無い場合は ephemeral でエラー応答 (副作用なし)
* セッションがある場合は embed を公開応答で送信
* タスクのクリア状態が embed の表示記号に反映される
* タスクの ``current`` / ``set_value`` が embed に表示される
* タスクの ``value`` が None のときは値部分が省略される
* 25 タスクのような長い一覧でも description の上限を超えない
* setup() で cog が Bot に登録される
"""

import asyncio
from datetime import datetime, timezone
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from src.cogs.show_progress import ShowProgressCog, setup
from src.services.session import Session
from src.services.session_manager import SessionManager
from src.services.task import Task
from tests.cogs.conftest import make_mock_interaction


# ==================================================
# 型検査回避ヘルパー
# ==================================================
def _invoke_progress(cog: ShowProgressCog, interaction: Any) -> Any:
    """`/progress` の素のコールバックを呼び出す薄いラッパ"""
    callback = cast(Any, cog.progress).callback
    return callback(cog, interaction)


# ==================================================
# 共通ヘルパー
# ==================================================
def _make_session(tasks: list[Task]) -> Session:
    """SessionManager に登録するテスト用セッションを生成する"""
    return Session(
        song_name="Magnolia",
        panel_count=len(tasks),
        tasks=tasks,
        channel_id=2001,
        owner_id=1001,
        started_at=datetime(2026, 5, 7, tzinfo=timezone.utc),
    )


def _make_cog() -> ShowProgressCog:
    """テスト用 `ShowProgressCog` を生成する (依存無し)"""
    bot = MagicMock()
    return ShowProgressCog(bot=bot)


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
class TestProgressWithoutActiveSession:
    """セッションが存在しないとき: ephemeral でエラー応答し副作用を起こさない"""

    def test_responds_ephemeral_when_no_session(self):
        cog = _make_cog()
        interaction = make_mock_interaction()

        async def run() -> None:
            await _invoke_progress(cog, interaction)

        asyncio.run(run())

        # ephemeral でエラー応答
        interaction.response.send_message.assert_awaited_once()
        _, kwargs = interaction.response.send_message.call_args
        assert kwargs.get("ephemeral") is True
        # defer / followup は呼ばれない (早期終了)
        interaction.response.defer.assert_not_called()
        interaction.followup.send.assert_not_called()
        # SessionManager は依然 None (no-op)
        assert SessionManager.instance().is_active() is False


# ==================================================
# セッション有り (Happy Path)
# ==================================================
class TestProgressHappyPath:
    """進行中セッションがある場合: 公開応答で embed を送信する"""

    def test_sends_public_embed_with_task_progress(self):
        cog = _make_cog()
        # cleared 1 件 / 未 cleared 2 件 を含むタスクを用意
        tasks = [
            Task(type="level", set_value=1, value=5, current=1),  # cleared
            Task(type="title_include", set_value=3, value=["a", "b"], current=1),
            Task(type="level_total", set_value=100, value=None, current=20),
        ]
        session = _make_session(tasks)
        SessionManager.instance().start(session)

        interaction = make_mock_interaction()

        async def run() -> None:
            await _invoke_progress(cog, interaction)

        asyncio.run(run())

        # 公開応答 (defer なし / send_message)
        interaction.response.defer.assert_not_called()
        interaction.response.send_message.assert_awaited_once()
        _, kwargs = interaction.response.send_message.call_args

        # ephemeral は指定なし (= 公開)
        assert kwargs.get("ephemeral") is None or kwargs.get("ephemeral") is False

        # embed が渡される
        embed = kwargs.get("embed")
        assert isinstance(embed, discord.Embed)

        # タイトルにクリア数が反映される
        assert embed.title is not None
        assert "1/3" in embed.title

        # description に各タスクが 1 行ずつ含まれる
        description = embed.description or ""
        # cleared タスク: ✓ + 1/1
        assert "✓ 1. level (5): 1/1" in description
        # 未 cleared タスク (value あり)
        assert "□ 2. title_include (['a', 'b']): 1/3" in description
        # 未 cleared タスク (value None) → value 部分は省略
        assert "□ 3. level_total: 20/100" in description
        # value が None のタスクには `()` が出現しないこと
        assert "level_total ()" not in description

    def test_all_cleared_tasks_use_cleared_symbol(self):
        """全タスク cleared なら全行が ✓ で始まり、タイトルが N/N となる"""
        cog = _make_cog()
        tasks = [
            Task(type="level", set_value=1, value=5, current=1),
            Task(type="version", set_value=1, value=None, current=1),
        ]
        SessionManager.instance().start(_make_session(tasks))
        interaction = make_mock_interaction()

        async def run() -> None:
            await _invoke_progress(cog, interaction)

        asyncio.run(run())

        _, kwargs = interaction.response.send_message.call_args
        embed = kwargs["embed"]
        description = embed.description or ""

        # 全行 cleared 記号
        assert description.count("✓ ") == 2
        assert "□ " not in description
        # タイトルに 2/2 が含まれる
        assert "2/2" in (embed.title or "")

    def test_no_cleared_tasks_use_unclear_symbol_only(self):
        """未 cleared のみなら全行が □ で始まり、タイトルが 0/N となる"""
        cog = _make_cog()
        tasks = [
            Task(type="level", set_value=3, value=5, current=0),
            Task(type="title_include", set_value=2, value=["a"], current=0),
        ]
        SessionManager.instance().start(_make_session(tasks))
        interaction = make_mock_interaction()

        async def run() -> None:
            await _invoke_progress(cog, interaction)

        asyncio.run(run())

        _, kwargs = interaction.response.send_message.call_args
        embed = kwargs["embed"]
        description = embed.description or ""

        assert description.count("□ ") == 2
        assert "✓ " not in description
        assert "0/2" in (embed.title or "")


# ==================================================
# 上限ガード
# ==================================================
class TestProgressDescriptionLimit:
    """description は Discord 仕様 (4096 文字) を超えてはならない"""

    def test_description_truncated_when_too_long(self):
        cog = _make_cog()
        # 1 行を意図的に長くしたタスクを 25 件 (パネル最大数) 作って 4096 文字超を狙う
        long_value = "x" * 500  # 1 行 ~520 文字 → 25 行で ~13000 文字
        tasks = [
            Task(type=f"type_{i}", set_value=2, value=long_value, current=0)
            for i in range(25)
        ]
        SessionManager.instance().start(_make_session(tasks))
        interaction = make_mock_interaction()

        async def run() -> None:
            await _invoke_progress(cog, interaction)

        asyncio.run(run())

        _, kwargs = interaction.response.send_message.call_args
        embed = kwargs["embed"]
        description = embed.description or ""

        # description は上限 (4096) を超えない
        assert len(description) <= 4096
        # 切り詰めが発生したら末尾に省略記号 "…" が付く
        assert description.endswith("…")


# ==================================================
# extension setup
# ==================================================
class TestSetup:
    """`setup()` が呼ばれると cog が Bot に登録される"""

    def test_setup_adds_cog(self):
        bot: Any = MagicMock()
        bot.add_cog = AsyncMock()

        async def run() -> None:
            await setup(bot)

        asyncio.run(run())

        bot.add_cog.assert_awaited_once()
        added_cog = bot.add_cog.call_args.args[0]
        assert isinstance(added_cog, ShowProgressCog)
