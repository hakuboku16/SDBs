"""
src/cogs/_helpers.py のユニットテスト

`build_song_autocomplete` が `SongRepository.search_partial` の結果を
`app_commands.Choice[str]` 列に変換することを検証します。
合わせて `tests/cogs/conftest.py` の `make_mock_interaction` が
最低限必要な属性 (`response.send_message` / `followup.send` 等) を備えていることも確認します。
"""

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from discord import app_commands

from src.cogs._helpers import (
    TOPIC_CLEARED_SYMBOL,
    TOPIC_NOT_CLEARED_SYMBOL,
    build_song_autocomplete,
    build_topic_field,
)
from src.services.song_repository import Song, SongRepository
from src.utils.helpers import get_absolute_path
from tests.conftest import make_task
from tests.cogs.conftest import make_mock_interaction


# ==================================================
# fixtures
# ==================================================
@pytest.fixture
def real_repo() -> SongRepository:
    """
    実 JSON を読み込んだ SongRepository

    オートコンプリート挙動の検証では実データの楽曲名で部分一致できることを確認したい。
    """
    return SongRepository(
        songs_json=get_absolute_path("assets/data/all_songs.json"),
        images_dir=get_absolute_path("assets/images"),
    )


def _run(coro: Any) -> Any:
    """asyncio.run の薄いラッパ"""
    return asyncio.run(coro)


# ==================================================
# build_song_autocomplete
# ==================================================
class TestBuildSongAutocomplete:
    """`build_song_autocomplete` の振る舞い"""

    def test_returns_choices_for_partial_match(self, real_repo: SongRepository):
        """
        部分一致クエリに対して Choice 列を返す
        (実 JSON の楽曲名から検証)
        """
        # 実データの中から確実に存在するクエリを 1 件選ぶ
        sample_name = real_repo.all()[0].name
        # 部分文字列を 2-3 文字で抽出 (短すぎると 25 件超過で打ち切られる可能性があるが、
        # ここでは「sample_name 自身が候補に含まれること」だけを検証する)
        query = sample_name[:2] if len(sample_name) >= 2 else sample_name

        autocomplete = build_song_autocomplete(real_repo)
        interaction = make_mock_interaction()

        choices = _run(autocomplete(interaction, query))

        # 全要素が Choice であり、name == value で楽曲名が入っている
        assert all(isinstance(c, app_commands.Choice) for c in choices)
        assert all(c.name == c.value for c in choices)
        # クエリで部分一致するものに sample_name が含まれている
        assert any(c.value == sample_name for c in choices)

    def test_empty_query_returns_first_n_songs(self, real_repo: SongRepository):
        """
        空クエリでは先頭から `AUTOCOMPLETE_LIMIT` 件 (= 25) までを返す
        """
        autocomplete = build_song_autocomplete(real_repo)
        interaction = make_mock_interaction()

        choices = _run(autocomplete(interaction, ""))

        # 上限以下に収まる
        assert len(choices) <= SongRepository.AUTOCOMPLETE_LIMIT
        # 楽曲が 25 件以上あるなら上限ぴったり
        if len(real_repo) >= SongRepository.AUTOCOMPLETE_LIMIT:
            assert len(choices) == SongRepository.AUTOCOMPLETE_LIMIT
        # 先頭から順に並ぶ (search_partial の仕様に追従)
        first_song = real_repo.all()[0]
        assert choices[0].value == first_song.name

    def test_no_match_returns_empty_list(self, tmp_path: Path):
        """
        どの楽曲にも一致しないクエリでは空リストを返す
        """
        # 楽曲が 1 件だけの最小 JSON を組み立てる
        songs_json = tmp_path / "songs.json"
        songs_json.write_text(
            '{"shelfA":{"bookA":{"OnlySong":{'
            '"VERSION":"v1","LEVEL":{"Easy":1},"NOTES":{"Easy":100},'
            '"TIME":120,"COMPOSER":["X"]}}}}',
            encoding="utf-8",
        )
        repo = SongRepository(songs_json=songs_json, images_dir=tmp_path)

        autocomplete = build_song_autocomplete(repo)
        interaction = make_mock_interaction()

        choices = _run(autocomplete(interaction, "ZZZ_NOT_PRESENT_ZZZ"))
        assert choices == []

    def test_choice_count_does_not_exceed_autocomplete_limit(
        self, real_repo: SongRepository
    ):
        """
        Discord の仕様上の最大件数 (25) を超えないこと
        """
        autocomplete = build_song_autocomplete(real_repo)
        interaction = make_mock_interaction()

        # 全件が候補になり得るような短いクエリ (1 文字で大量にヒットするケースを想定)
        # 万一マッチしなくてもこのテストの主眼は上限超過しないことなので問題ない
        choices = _run(autocomplete(interaction, "a"))
        assert len(choices) <= SongRepository.AUTOCOMPLETE_LIMIT


# ==================================================
# build_topic_field
# ==================================================
class TestBuildTopicField:
    """`build_topic_field` の振る舞い (`/start` `/play` `/progress` 共通フォーマット)"""

    def test_uncleared_task_uses_unclear_symbol(self):
        """未 cleared のタスクは ⬜ で始まる name と format_description の value を返す"""
        task = make_task(
            type="level",
            set_value=3,
            value=5,
            current=1,
            play_quality="プレイ",
            description_template="Lv.valueの譜面を持つ楽曲をset回play",
        )
        name, value = build_topic_field(0, task)
        # symbol + 1-origin index + (current/set)
        assert name == f"{TOPIC_NOT_CLEARED_SYMBOL} パネル 1 (1/3)"
        # value は format_description (placeholder 置換済)
        assert value == "Lv.5の譜面を持つ楽曲を3回プレイ"

    def test_cleared_task_uses_cleared_symbol(self):
        """cleared 済みのタスクは ✅ で始まる name を返す"""
        task = make_task(
            type="level",
            set_value=1,
            value=5,
            current=1,
            play_quality="プレイ",
            description_template="Lv.valueの譜面を持つ楽曲をset回play",
        )
        name, _ = build_topic_field(2, task)
        # 既に cleared で初期化されている
        assert task.cleared is True
        assert name == f"{TOPIC_CLEARED_SYMBOL} パネル 3 (1/1)"

    def test_field_value_truncated_when_too_long(self):
        """value が 1024 文字を超えるテンプレートは末尾を省略マーカーで切り詰める"""
        long_template = "x" * 2000  # 1024 を大幅に超える
        task = make_task(
            type="dummy",
            set_value=1,
            value=None,
            current=0,
            description_template=long_template,
        )
        _, value = build_topic_field(0, task)
        # Discord の field value 上限 (1024) に収まる
        assert len(value) <= 1024
        # 切り詰め時は末尾に省略記号が付く
        assert value.endswith("…")


# ==================================================
# make_mock_interaction (conftest)
# ==================================================
class TestMockInteraction:
    """
    conftest の `make_mock_interaction` が最低限の振る舞いを備えていることを確認する
    (5.2 以降の cog テストが依存するヘルパーの自己テスト)
    """

    def test_has_user_attributes(self):
        """user.id / user.display_name / user.name が指定値で設定される"""
        interaction = make_mock_interaction(user_id=42, user_name="alice")
        assert interaction.user.id == 42
        assert interaction.user.display_name == "alice"
        assert interaction.user.name == "alice"

    def test_has_channel_and_guild_ids(self):
        """channel_id / guild_id / channel.id が指定値で設定される"""
        interaction = make_mock_interaction(channel_id=12, guild_id=34)
        assert interaction.channel_id == 12
        assert interaction.guild_id == 34
        assert interaction.channel.id == 12

    def test_response_send_message_is_async_mock(self):
        """response.send_message は AsyncMock で、await して呼び出し検証ができる"""
        interaction = make_mock_interaction()

        async def call() -> None:
            await interaction.response.send_message("hello", ephemeral=True)

        _run(call())
        interaction.response.send_message.assert_awaited_once_with("hello", ephemeral=True)

    def test_followup_send_is_async_mock(self):
        """followup.send は AsyncMock"""
        interaction = make_mock_interaction()

        async def call() -> None:
            await interaction.followup.send("done", ephemeral=True)

        _run(call())
        interaction.followup.send.assert_awaited_once_with("done", ephemeral=True)

    def test_response_is_done_default_is_false(self):
        """response.is_done() のデフォルトは False"""
        interaction = make_mock_interaction()
        assert interaction.response.is_done() is False

    def test_response_is_done_can_be_overridden(self):
        """`is_response_done=True` で is_done() が True を返す"""
        interaction = make_mock_interaction(is_response_done=True)
        assert interaction.response.is_done() is True

    def test_command_attribute_can_be_set(self):
        """command_name 指定時は qualified_name にその値が入る"""
        interaction = make_mock_interaction(command_name="answer")
        assert interaction.command is not None
        assert interaction.command.qualified_name == "answer"

    def test_command_attribute_is_none_by_default(self):
        """command_name 未指定時は command 属性自体が None"""
        interaction = make_mock_interaction()
        assert interaction.command is None


# ==================================================
# 補助: Song dataclass のサンプル生成 (将来テストのため)
# ==================================================
def _sample_song(name: str = "Sample") -> Song:
    """
    dataclass フィールドの最小指定で `Song` を組み立てる (このファイルでは未使用だが、
    cog テスト全般で参考になるユーティリティとして残す)
    """
    return Song(
        name=name,
        shelf="shelfA",
        book="bookA",
        version="v1",
        time=120,
        composer=["X"],
        levels={"Easy": 1},
        notes={"Easy": 100},
    )
