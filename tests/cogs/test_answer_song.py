"""
src/cogs/answer_song.py のユニットテスト

`/answer` コマンドの主な振る舞いを検証します:

* 進行中セッションが無い場合は ephemeral でエラー応答
* `SongRepository` に存在しない楽曲名は ephemeral でエラー応答
* 正解時: ephemeral で「🎉 正解です！」title と「正解: {song}」description を返し、
  `Session.correct_answerers` に登録される
* 不正解時: ephemeral で「❌ 不正解です」title と「あなたの回答: {song}」description を返し、
  `Session.correct_answerers` には登録されない
* 同一ユーザーの正解は重複登録されない (冪等性)
* 正解/不正解にかかわらずセッションは終了しない (`/answer` 仕様)
* 全回答は `Session.answer_records` に時系列で蓄積される (`/end` の集計用)
* 楽曲名オートコンプリートが `SongRepository.search_partial` を介して候補を返す

`discord.Interaction` は読み取り専用属性が多いため `tests/cogs/conftest.py` の
`make_mock_interaction` で擬似 Interaction を生成します。
"""

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional, cast
from unittest.mock import MagicMock

import pytest
from discord import app_commands

from src.cogs.answer_song import AnswerSongCog
from src.services.session import Session
from src.services.session_manager import SessionManager
from src.services.song_repository import Song
from src.services.task import Task
from tests.cogs.conftest import make_mock_interaction
from tests.conftest import make_task


# ==================================================
# 型検査回避ヘルパー
# ==================================================
def _invoke_answer(
    cog: AnswerSongCog,
    interaction: Any,
    *,
    song: str = "SampleSong",
) -> Any:
    """`/answer` の素のコールバックを呼び出す薄いラッパ"""
    callback = cast(Any, cog.answer).callback
    return callback(cog, interaction, song=song)


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
        levels={"Easy": 1, "Normal": 3, "Hard": 5, "Extra": 7},
        notes={"Easy": 50, "Normal": 100, "Hard": 200, "Extra": 300},
    )


def _make_session(
    *,
    song_name: str = "SampleSong",
    tasks: Optional[list[Task]] = None,
) -> Session:
    """`SessionManager` に登録するテスト用セッションを生成する"""
    return Session(
        song_name=song_name,
        panel_count=1 if tasks is None else len(tasks),
        tasks=tasks if tasks is not None else [make_task(type="level", set_value=1, value=5)],
        channel_id=2001,
        owner_id=1001,
        started_at=datetime(2026, 5, 7, tzinfo=timezone.utc),
        pinned_message_id=999_111,
    )


def _make_cog(
    *,
    songs: Optional[list[Song]] = None,
) -> AnswerSongCog:
    """全依存を mock 化した `AnswerSongCog` を組み立てる"""
    bot = MagicMock()

    repo = MagicMock()
    catalog: list[Song] = songs if songs is not None else [_sample_song()]
    repo.all = MagicMock(return_value=catalog)
    repo.find_by_name = MagicMock(
        side_effect=lambda name: next(
            (s for s in catalog if s.name == name), None
        )
    )
    repo.search_partial = MagicMock(
        side_effect=lambda q, limit=25: [
            s for s in catalog if q.casefold() in s.name.casefold()
        ][:limit]
    )

    return AnswerSongCog(bot=bot, song_repository=repo)


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
# 早期失敗 (セッション無し / 楽曲未知)
# ==================================================
class TestEarlyValidation:
    """早期失敗パスは ephemeral でエラー応答し副作用を残さない"""

    def test_no_active_session_returns_ephemeral_error(self):
        cog = _make_cog()
        # SessionManager は空
        interaction = make_mock_interaction()

        async def run() -> None:
            await _invoke_answer(cog, interaction)

        asyncio.run(run())

        interaction.response.send_message.assert_awaited_once()
        _, kwargs = interaction.response.send_message.call_args
        assert kwargs.get("ephemeral") is True
        # SessionManager は依然 None
        assert SessionManager.instance().current() is None

    def test_unknown_song_returns_ephemeral_error(self):
        cog = _make_cog(songs=[_sample_song("KnownSong")])
        SessionManager.instance().start(_make_session(song_name="KnownSong"))
        interaction = make_mock_interaction()

        async def run() -> None:
            # 未知の楽曲名で呼ぶ
            await _invoke_answer(cog, interaction, song="UnknownSong")

        asyncio.run(run())

        interaction.response.send_message.assert_awaited_once()
        _, kwargs = interaction.response.send_message.call_args
        assert kwargs.get("ephemeral") is True
        # 履歴は登録されない
        session = SessionManager.instance().current()
        assert session is not None
        assert session.answer_records == []
        assert session.correct_answerers == set()


# ==================================================
# 正解 / 不正解判定
# ==================================================
class TestAnswerJudgement:
    """正解判定と ephemeral 応答内容を検証する"""

    def test_correct_answer_returns_ephemeral_success_message(self):
        """正解時: 🎉 title と祝福 description が embed として本人にのみ ephemeral で返る"""
        cog = _make_cog(songs=[_sample_song("SampleSong")])
        SessionManager.instance().start(_make_session(song_name="SampleSong"))
        interaction = make_mock_interaction(
            user_id=42, user_name="Alice"
        )

        async def run() -> None:
            await _invoke_answer(cog, interaction, song="SampleSong")

        asyncio.run(run())

        interaction.response.send_message.assert_awaited_once()
        _, kwargs = interaction.response.send_message.call_args
        # Bot からの送信は embed 統一。title に「正解」、description に曲名と祝福文言。
        import discord as _discord
        embed = kwargs.get("embed")
        assert isinstance(embed, _discord.Embed)
        title: str = embed.title or ""
        description: str = embed.description or ""
        assert "🎉" in title
        assert "正解" in title
        assert "SampleSong" in description
        assert "おめでとう" in description
        assert kwargs.get("ephemeral") is True

    def test_incorrect_answer_returns_ephemeral_failure_message(self):
        """不正解時: ❌ title と再挑戦 description が embed として本人にのみ ephemeral で返る"""
        cog = _make_cog(
            songs=[_sample_song("SampleSong"), _sample_song("WrongSong")]
        )
        SessionManager.instance().start(_make_session(song_name="SampleSong"))
        interaction = make_mock_interaction(user_id=42, user_name="Alice")

        async def run() -> None:
            await _invoke_answer(cog, interaction, song="WrongSong")

        asyncio.run(run())

        interaction.response.send_message.assert_awaited_once()
        _, kwargs = interaction.response.send_message.call_args
        import discord as _discord
        embed = kwargs.get("embed")
        assert isinstance(embed, _discord.Embed)
        title: str = embed.title or ""
        description: str = embed.description or ""
        assert "❌" in title
        assert "不正解" in title
        assert "WrongSong" in description
        assert "残念" in description
        assert kwargs.get("ephemeral") is True


# ==================================================
# 正解者集合への登録
# ==================================================
class TestCorrectAnswerersRegistration:
    """`Session.correct_answerers` への登録規則を検証する"""

    def test_correct_answer_registers_user(self):
        """正解時に (user_id, user_name) が正解者集合に追加される"""
        cog = _make_cog(songs=[_sample_song("SampleSong")])
        SessionManager.instance().start(_make_session(song_name="SampleSong"))
        interaction = make_mock_interaction(user_id=42, user_name="Alice")

        async def run() -> None:
            await _invoke_answer(cog, interaction, song="SampleSong")

        asyncio.run(run())

        session = SessionManager.instance().current()
        assert session is not None
        assert (42, "Alice") in session.correct_answerers

    def test_incorrect_answer_does_not_register_user(self):
        """不正解時は正解者集合へ追加しない"""
        cog = _make_cog(
            songs=[_sample_song("SampleSong"), _sample_song("WrongSong")]
        )
        SessionManager.instance().start(_make_session(song_name="SampleSong"))
        interaction = make_mock_interaction(user_id=42, user_name="Alice")

        async def run() -> None:
            await _invoke_answer(cog, interaction, song="WrongSong")

        asyncio.run(run())

        session = SessionManager.instance().current()
        assert session is not None
        assert session.correct_answerers == set()

    def test_same_user_correct_twice_is_idempotent(self):
        """同一ユーザーが 2 回正解しても集合のサイズは変わらない (冪等性)"""
        cog = _make_cog(songs=[_sample_song("SampleSong")])
        SessionManager.instance().start(_make_session(song_name="SampleSong"))
        interaction = make_mock_interaction(user_id=42, user_name="Alice")

        async def run() -> None:
            # 同じユーザーが連続で正解
            await _invoke_answer(cog, interaction, song="SampleSong")
            await _invoke_answer(cog, interaction, song="SampleSong")

        asyncio.run(run())

        session = SessionManager.instance().current()
        assert session is not None
        # 集合内の組は 1 件のみ
        assert session.correct_answerers == {(42, "Alice")}

    def test_multiple_users_correct_all_registered(self):
        """異なるユーザーは全員が正解者集合に登録される"""
        cog = _make_cog(songs=[_sample_song("SampleSong")])
        SessionManager.instance().start(_make_session(song_name="SampleSong"))
        interaction_a = make_mock_interaction(user_id=42, user_name="Alice")
        interaction_b = make_mock_interaction(user_id=99, user_name="Bob")

        async def run() -> None:
            await _invoke_answer(cog, interaction_a, song="SampleSong")
            await _invoke_answer(cog, interaction_b, song="SampleSong")

        asyncio.run(run())

        session = SessionManager.instance().current()
        assert session is not None
        assert session.correct_answerers == {(42, "Alice"), (99, "Bob")}


# ==================================================
# 履歴蓄積 / セッション継続性
# ==================================================
class TestSessionContinuity:
    """`/answer` がセッションを終了させず、回答履歴のみ蓄積することを検証する"""

    def test_correct_answer_does_not_end_session(self):
        """正解してもセッションは終了しない"""
        cog = _make_cog(songs=[_sample_song("SampleSong")])
        SessionManager.instance().start(_make_session(song_name="SampleSong"))
        interaction = make_mock_interaction()

        async def run() -> None:
            await _invoke_answer(cog, interaction, song="SampleSong")

        asyncio.run(run())

        # セッションは依然進行中
        assert SessionManager.instance().current() is not None

    def test_incorrect_answer_does_not_end_session(self):
        """不正解でもセッションは終了しない"""
        cog = _make_cog(
            songs=[_sample_song("SampleSong"), _sample_song("WrongSong")]
        )
        SessionManager.instance().start(_make_session(song_name="SampleSong"))
        interaction = make_mock_interaction()

        async def run() -> None:
            await _invoke_answer(cog, interaction, song="WrongSong")

        asyncio.run(run())

        assert SessionManager.instance().current() is not None

    def test_answer_records_accumulate_in_order(self):
        """全回答 (○/×) は `Session.answer_records` に時系列で蓄積される"""
        cog = _make_cog(
            songs=[_sample_song("SampleSong"), _sample_song("WrongSong")]
        )
        SessionManager.instance().start(_make_session(song_name="SampleSong"))
        interaction_a = make_mock_interaction(user_id=42, user_name="Alice")
        interaction_b = make_mock_interaction(user_id=99, user_name="Bob")

        async def run() -> None:
            await _invoke_answer(cog, interaction_a, song="WrongSong")
            await _invoke_answer(cog, interaction_b, song="SampleSong")
            await _invoke_answer(cog, interaction_a, song="SampleSong")

        asyncio.run(run())

        session = SessionManager.instance().current()
        assert session is not None
        assert len(session.answer_records) == 3
        # 1 件目: Alice 不正解
        assert session.answer_records[0].user_id == 42
        assert session.answer_records[0].song_name == "WrongSong"
        assert session.answer_records[0].correct is False
        # 2 件目: Bob 正解
        assert session.answer_records[1].user_id == 99
        assert session.answer_records[1].song_name == "SampleSong"
        assert session.answer_records[1].correct is True
        # 3 件目: Alice 正解
        assert session.answer_records[2].user_id == 42
        assert session.answer_records[2].correct is True

    def test_no_public_followup_sent(self):
        """`/answer` は公開チャンネルへの followup を行わない"""
        cog = _make_cog(songs=[_sample_song("SampleSong")])
        SessionManager.instance().start(_make_session(song_name="SampleSong"))
        interaction = make_mock_interaction()

        async def run() -> None:
            await _invoke_answer(cog, interaction, song="SampleSong")

        asyncio.run(run())

        # defer / followup のいずれも呼ばれない (公開応答なし)
        interaction.response.defer.assert_not_called()
        interaction.followup.send.assert_not_called()


# ==================================================
# 楽曲名オートコンプリート
# ==================================================
class TestSongAutocomplete:
    """`SongRepository.search_partial` 経由で部分一致候補を返す"""

    def test_autocomplete_returns_partial_matches(self):
        cog = _make_cog(
            songs=[
                _sample_song("Magnolia"),
                _sample_song("Aleph-0"),
                _sample_song("Saika"),
            ]
        )
        interaction = make_mock_interaction()
        callback = cast(Any, cog._song_autocomplete_callback)

        async def run() -> list[app_commands.Choice[str]]:
            return await callback(interaction, "ai")

        choices = asyncio.run(run())

        names = [c.name for c in choices]
        # "Saika" のみが "ai" を含む (大文字小文字無視)
        assert names == ["Saika"]

    def test_autocomplete_empty_query_returns_all_within_limit(self):
        catalog = [_sample_song(f"Song{i}") for i in range(30)]
        cog = _make_cog(songs=catalog)
        interaction = make_mock_interaction()
        callback = cast(Any, cog._song_autocomplete_callback)

        async def run() -> list[app_commands.Choice[str]]:
            return await callback(interaction, "")

        choices = asyncio.run(run())

        # 上限 25 件まで
        assert len(choices) == 25
