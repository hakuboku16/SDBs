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
from tests.conftest import make_task


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
            make_task(
                type="level",
                set_value=1,
                value=5,
                current=1,
                play_quality="プレイ",
                description_template="Lv.valueの譜面を持つ楽曲をset回play",
            ),  # cleared
            make_task(
                type="title_include",
                set_value=3,
                value=["a", "b"],
                current=1,
                play_quality="AC",
                description_template="楽曲名にvalueのすべてが含まれる楽曲をset回play",
            ),
            make_task(
                type="level_total",
                set_value=100,
                value=None,
                current=20,
                play_quality="プレイ",
                description_template="playした譜面のレベルの合計がset",
            ),
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

        # タイトルにクリア数 + 絵文字が反映される
        assert embed.title is not None
        assert "📊" in embed.title
        assert "1/3" in embed.title

        # 各タスクは 1 件 1 field で並ぶ (0-origin の index)
        assert len(embed.fields) == 3
        # cleared タスク: ✅ + 0-origin index 0 + (1/1) + 整形済み description
        assert embed.fields[0].name == "✅ パネル 0 (1/1)"
        assert embed.fields[0].value == "Lv.5の譜面を持つ楽曲を1回プレイ"
        # 未 cleared タスク (value list, AC quality)
        assert embed.fields[1].name == "⬜ パネル 1 (1/3)"
        assert (
            embed.fields[1].value
            == "楽曲名に(a, b)のすべてが含まれる楽曲を3回AC"
        )
        # 未 cleared タスク (value None / 累積系)
        assert embed.fields[2].name == "⬜ パネル 2 (20/100)"
        assert embed.fields[2].value == "プレイした譜面のレベルの合計が100"

    def test_all_cleared_tasks_use_cleared_symbol(self):
        """全タスク cleared なら全 field name が ✅ で始まり、タイトルが N/N となる"""
        cog = _make_cog()
        tasks = [
            make_task(type="level", set_value=1, value=5, current=1),
            make_task(type="version", set_value=1, value=None, current=1),
        ]
        SessionManager.instance().start(_make_session(tasks))
        interaction = make_mock_interaction()

        async def run() -> None:
            await _invoke_progress(cog, interaction)

        asyncio.run(run())

        _, kwargs = interaction.response.send_message.call_args
        embed = kwargs["embed"]

        # 全 field cleared 記号
        assert len(embed.fields) == 2
        assert all(
            f.name is not None and f.name.startswith("✅ ") for f in embed.fields
        )
        # タイトルに 2/2 が含まれる
        assert "2/2" in (embed.title or "")

    def test_no_cleared_tasks_use_unclear_symbol_only(self):
        """未 cleared のみなら全 field name が ⬜ で始まり、タイトルが 0/N となる"""
        cog = _make_cog()
        tasks = [
            make_task(type="level", set_value=3, value=5, current=0),
            make_task(type="title_include", set_value=2, value=["a"], current=0),
        ]
        SessionManager.instance().start(_make_session(tasks))
        interaction = make_mock_interaction()

        async def run() -> None:
            await _invoke_progress(cog, interaction)

        asyncio.run(run())

        _, kwargs = interaction.response.send_message.call_args
        embed = kwargs["embed"]

        assert len(embed.fields) == 2
        assert all(
            f.name is not None and f.name.startswith("⬜ ") for f in embed.fields
        )
        assert "0/2" in (embed.title or "")


# ==================================================
# 上限ガード
# ==================================================
class TestProgressFieldLimit:
    """パネル最大数 (25) でも Discord の field 数上限 (25) を超えない"""

    def test_25_panels_fit_within_field_limit(self):
        """25 パネルは 25 fields にちょうど収まる (上限超過なし)"""
        cog = _make_cog()
        tasks = [
            make_task(
                type=f"type_{i}",
                set_value=2,
                value=f"v{i}",
                current=0,
                description_template="value (set, play)",
            )
            for i in range(25)
        ]
        SessionManager.instance().start(_make_session(tasks))
        interaction = make_mock_interaction()

        async def run() -> None:
            await _invoke_progress(cog, interaction)

        asyncio.run(run())

        _, kwargs = interaction.response.send_message.call_args
        embed = kwargs["embed"]
        # Discord 仕様の field 数上限 (25) を超えない
        assert len(embed.fields) == 25


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
