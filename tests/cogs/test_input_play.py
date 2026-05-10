"""
src/cogs/input_play.py のユニットテスト

`/play` コマンドの主な振る舞いを検証します:

* charming / combo の自然数バリデーション (ephemeral 拒否、副作用なし)
* 進行中セッションが無い場合は ephemeral でエラー応答
* `SongRepository` に存在しない楽曲名は ephemeral でエラー応答
* Happy Path: `PlayRecord` がセッションに追加され、タスク評価結果が embed で返る
* 進捗があった場合は ``current`` / ``set_value`` が embed に反映される
* 新規 cleared が発生したらピン留めメッセージの添付画像が差し替えられる
* 新規 cleared が無いときは画像合成・メッセージ編集が呼ばれない
* 楽曲名オートコンプリートが `SongRepository.search_partial` を介して候補を返す

`discord.Interaction` は読み取り専用属性が多いため `tests/cogs/conftest.py` の
`make_mock_interaction` で擬似 Interaction を生成します。
"""

import asyncio
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Optional, cast
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from discord import app_commands

from src.cogs.input_play import InputPlayCog
from src.services.session import PlayRecord, Session
from src.services.session_manager import SessionManager
from src.services.song_repository import Song
from src.services.task import Task
from src.services.task_evaluator import TaskEvaluator
from tests.cogs.conftest import make_mock_interaction
from tests.conftest import make_task


# ==================================================
# 型検査回避ヘルパー
# ==================================================
def _invoke_play(
    cog: InputPlayCog,
    interaction: Any,
    *,
    song: str = "SampleSong",
    difficulty: app_commands.Choice[str] = app_commands.Choice(
        name="Hard", value="Hard"
    ),
    charming: int = 100,
    combo: int = 200,
) -> Any:
    """`/play` の素のコールバックを呼び出す薄いラッパ"""
    callback = cast(Any, cog.play).callback
    return callback(
        cog,
        interaction,
        song=song,
        difficulty=difficulty,
        charming=charming,
        combo=combo,
    )


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


def _make_session(tasks: list[Task], *, song_name: str = "SampleSong") -> Session:
    """`SessionManager` に登録するテスト用セッションを生成する"""
    return Session(
        song_name=song_name,
        panel_count=len(tasks),
        tasks=tasks,
        channel_id=2001,
        owner_id=1001,
        started_at=datetime(2026, 5, 7, tzinfo=timezone.utc),
        pinned_message_id=999_111,
    )


def _make_cog(
    *,
    songs: Optional[list[Song]] = None,
    image_bytes: bytes = b"PNG_DATA",
    evaluator: Optional[TaskEvaluator] = None,
) -> InputPlayCog:
    """全依存を mock 化した `InputPlayCog` を組み立てる"""
    bot = MagicMock()

    repo = MagicMock()
    catalog: list[Song] = songs if songs is not None else [_sample_song()]
    repo.all = MagicMock(return_value=catalog)
    repo.find_by_name = MagicMock(
        side_effect=lambda name: next(
            (s for s in catalog if s.name == name), None
        )
    )
    # autocomplete 経由の候補解決でも search_partial が呼ばれるため最低限備える
    repo.search_partial = MagicMock(
        side_effect=lambda q, limit=25: [
            s for s in catalog if q.casefold() in s.name.casefold()
        ][:limit]
    )

    proc = MagicMock()
    proc.compose = MagicMock(side_effect=lambda **_: BytesIO(image_bytes))

    return InputPlayCog(
        bot=bot,
        song_repository=repo,
        task_evaluator=evaluator if evaluator is not None else TaskEvaluator(),
        image_processor=proc,
    )


def _attach_pinned_message(
    interaction: MagicMock, *, message_id: int = 999_111
) -> MagicMock:
    """`interaction.channel.fetch_message` をピン留めメッセージ風 mock に差し替える"""
    pinned = MagicMock()
    pinned.id = message_id
    pinned.edit = AsyncMock()
    interaction.channel.fetch_message = AsyncMock(return_value=pinned)
    return pinned


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
# 早期失敗 (バリデーション / セッション無し / 楽曲未知)
# ==================================================
class TestEarlyValidation:
    """defer 前の早期失敗パスは ephemeral でエラー応答し副作用を残さない"""

    def test_invalid_charming_returns_ephemeral_error(self):
        cog = _make_cog()
        # セッションを登録しておき、charming バリデーションが先に走ることを確認
        SessionManager.instance().start(
            _make_session([make_task(type="level", set_value=1, value=5)])
        )
        interaction = make_mock_interaction()

        async def run() -> None:
            await _invoke_play(cog, interaction, charming=0)

        asyncio.run(run())

        interaction.response.send_message.assert_awaited_once()
        _, kwargs = interaction.response.send_message.call_args
        assert kwargs.get("ephemeral") is True
        # defer / followup は呼ばれない
        interaction.response.defer.assert_not_called()
        interaction.followup.send.assert_not_called()
        # PlayRecord は登録されない
        session = SessionManager.instance().current()
        assert session is not None
        assert session.play_records == []

    def test_invalid_combo_returns_ephemeral_error(self):
        cog = _make_cog()
        SessionManager.instance().start(
            _make_session([make_task(type="level", set_value=1, value=5)])
        )
        interaction = make_mock_interaction()

        async def run() -> None:
            await _invoke_play(cog, interaction, combo=-3)

        asyncio.run(run())

        interaction.response.send_message.assert_awaited_once()
        _, kwargs = interaction.response.send_message.call_args
        assert kwargs.get("ephemeral") is True
        interaction.response.defer.assert_not_called()

    def test_no_active_session_returns_ephemeral_error(self):
        cog = _make_cog()
        # SessionManager は空
        interaction = make_mock_interaction()

        async def run() -> None:
            await _invoke_play(cog, interaction)

        asyncio.run(run())

        interaction.response.send_message.assert_awaited_once()
        _, kwargs = interaction.response.send_message.call_args
        assert kwargs.get("ephemeral") is True
        interaction.response.defer.assert_not_called()
        # SessionManager は依然 None
        assert SessionManager.instance().current() is None

    def test_unknown_song_returns_ephemeral_error(self):
        cog = _make_cog(songs=[_sample_song("KnownSong")])
        SessionManager.instance().start(
            _make_session(
                [make_task(type="level", set_value=1, value=5)],
                song_name="KnownSong",
            )
        )
        interaction = make_mock_interaction()

        async def run() -> None:
            # 未知の楽曲名で呼ぶ
            await _invoke_play(cog, interaction, song="UnknownSong")

        asyncio.run(run())

        interaction.response.send_message.assert_awaited_once()
        _, kwargs = interaction.response.send_message.call_args
        assert kwargs.get("ephemeral") is True
        interaction.response.defer.assert_not_called()
        # PlayRecord は登録されない
        session = SessionManager.instance().current()
        assert session is not None
        assert session.play_records == []


# ==================================================
# Happy Path
# ==================================================
class TestHappyPath:
    """正常系: defer → PlayRecord 追加 → タスク評価 → embed 応答"""

    def test_play_record_added_to_session(self):
        cog = _make_cog()
        SessionManager.instance().start(
            _make_session([make_task(type="level", set_value=1, value=5)])
        )
        interaction = make_mock_interaction()
        _attach_pinned_message(interaction)

        async def run() -> None:
            await _invoke_play(
                cog,
                interaction,
                song="SampleSong",
                difficulty=app_commands.Choice(name="Hard", value="Hard"),
                charming=300,
                combo=400,
            )

        asyncio.run(run())

        session = SessionManager.instance().current()
        assert session is not None
        assert len(session.play_records) == 1
        rec: PlayRecord = session.play_records[0]
        assert rec.song_name == "SampleSong"
        assert rec.difficulty == "Hard"
        assert rec.charming == 300
        assert rec.combo == 400

    def test_defer_then_followup_embed_sent(self):
        cog = _make_cog()
        SessionManager.instance().start(
            _make_session([make_task(type="level", set_value=1, value=5)])
        )
        interaction = make_mock_interaction()
        _attach_pinned_message(interaction)

        async def run() -> None:
            await _invoke_play(cog, interaction)

        asyncio.run(run())

        # 公開応答 (defer + followup)
        interaction.response.defer.assert_awaited_once()
        interaction.followup.send.assert_awaited_once()
        _, kwargs = interaction.followup.send.call_args
        assert isinstance(kwargs.get("embed"), discord.Embed)

    def test_progressed_task_increments_current(self):
        """マッチ系タスクは current が +1 され、newly_cleared なら set_value に到達する"""
        cog = _make_cog()
        # set_value=1 / value=5 の "level" タスク → SampleSong は Hard=5 なのでマッチ
        task = make_task(type="level", set_value=1, value=5)
        SessionManager.instance().start(_make_session([task]))
        interaction = make_mock_interaction()
        _attach_pinned_message(interaction)

        async def run() -> None:
            await _invoke_play(cog, interaction)

        asyncio.run(run())

        # 進捗 +1 → cleared
        assert task.current == 1
        assert task.cleared is True

    def test_no_progress_when_task_does_not_match(self):
        """マッチしないタスクは current 据え置き / 進捗無しを embed に反映"""
        cog = _make_cog()
        # value=99 (どの難易度にも一致しない) の level タスク
        task = make_task(type="level", set_value=2, value=99)
        SessionManager.instance().start(_make_session([task]))
        interaction = make_mock_interaction()
        _attach_pinned_message(interaction)

        async def run() -> None:
            await _invoke_play(cog, interaction)

        asyncio.run(run())

        assert task.current == 0
        assert task.cleared is False
        # embed に「進捗のあったタスクはありません。」が含まれる
        _, kwargs = interaction.followup.send.call_args
        embed: discord.Embed = kwargs["embed"]
        assert embed.description is not None
        assert "進捗のあったタスクはありません" in embed.description

    def test_embed_lists_progressed_tasks(self):
        """進捗があったタスクのみ embed の field に列挙される"""
        cog = _make_cog()
        # マッチするタスク (level=5) と マッチしないタスク (level=99)
        match_task = make_task(
            type="level",
            set_value=2,
            value=5,
            description_template="Lv.valueの譜面を持つ楽曲をset回play",
            play_quality="プレイ",
        )
        no_match_task = make_task(
            type="level",
            set_value=2,
            value=99,
            description_template="Lv.valueの譜面を持つ楽曲をset回play",
            play_quality="プレイ",
        )
        SessionManager.instance().start(
            _make_session([match_task, no_match_task])
        )
        interaction = make_mock_interaction()
        _attach_pinned_message(interaction)

        async def run() -> None:
            await _invoke_play(cog, interaction)

        asyncio.run(run())

        _, kwargs = interaction.followup.send.call_args
        embed: discord.Embed = kwargs["embed"]

        # 進捗があったタスクのみ field に列挙される (1 件 1 field)
        assert len(embed.fields) == 1
        # 0-origin の index 0 のタスク (level=5) は進捗あり
        assert embed.fields[0].name is not None
        assert embed.fields[0].name.startswith("⬜ パネル 0 (1/2)")
        assert embed.fields[0].value == "Lv.5の譜面を持つ楽曲を2回プレイ"
        # マッチしないタスクの description は含まれない
        all_field_text: str = "\n".join(
            f"{f.name}\n{f.value}" for f in embed.fields
        )
        assert "Lv.99" not in all_field_text

    def test_newly_cleared_task_shows_clear_marker(self):
        """新規 cleared に到達したタスクは field name 末尾に [クリア!] が付く"""
        cog = _make_cog()
        # set_value=1 / value=5 → 一発で cleared
        task = make_task(
            type="level",
            set_value=1,
            value=5,
            description_template="Lv.valueの譜面を持つ楽曲をset回play",
            play_quality="プレイ",
        )
        SessionManager.instance().start(_make_session([task]))
        interaction = make_mock_interaction()
        _attach_pinned_message(interaction)

        async def run() -> None:
            await _invoke_play(cog, interaction)

        asyncio.run(run())

        _, kwargs = interaction.followup.send.call_args
        embed: discord.Embed = kwargs["embed"]
        assert len(embed.fields) == 1
        # cleared 済みのため symbol は ✅、末尾に "[クリア!]" マーカー
        assert embed.fields[0].name is not None
        assert embed.fields[0].name.startswith("✅ パネル 0 (1/1)")
        assert embed.fields[0].name.endswith("[クリア!]")


# ==================================================
# 画像再合成・メッセージ編集
# ==================================================
class TestPanelImageRefresh:
    """新規 cleared 発生 → 画像再合成 → ピン留めメッセージ編集の連鎖を検証する"""

    def test_image_recomposed_when_new_clear(self):
        """新規 cleared が起きたら ImageProcessor.compose と message.edit が呼ばれる"""
        cog = _make_cog()
        # set_value=1 → 一発で cleared に到達
        task = make_task(type="level", set_value=1, value=5)
        SessionManager.instance().start(_make_session([task]))
        interaction = make_mock_interaction()
        pinned = _attach_pinned_message(interaction)

        async def run() -> None:
            await _invoke_play(cog, interaction)

        asyncio.run(run())

        # compose は 1 回呼ばれる (再合成)
        proc = cast(Any, cog)._image_processor
        proc.compose.assert_called_once()
        # ピン留めメッセージが取得され編集される
        interaction.channel.fetch_message.assert_awaited_once_with(
            999_111
        )
        pinned.edit.assert_awaited_once()
        _, edit_kwargs = pinned.edit.call_args
        attachments = edit_kwargs.get("attachments")
        assert attachments is not None and len(attachments) == 1
        assert isinstance(attachments[0], discord.File)

    def test_image_not_recomposed_when_no_new_clear(self):
        """進捗のみ (cleared に到達せず) では画像再合成も編集も走らない"""
        cog = _make_cog()
        # set_value=3 → 1 回プレイでは cleared にならない
        task = make_task(type="level", set_value=3, value=5)
        SessionManager.instance().start(_make_session([task]))
        interaction = make_mock_interaction()
        pinned = _attach_pinned_message(interaction)

        async def run() -> None:
            await _invoke_play(cog, interaction)

        asyncio.run(run())

        # 進捗 +1 されたが cleared にはならない
        assert task.current == 1
        assert task.cleared is False
        # compose / fetch_message / edit のいずれも呼ばれない
        proc = cast(Any, cog)._image_processor
        proc.compose.assert_not_called()
        interaction.channel.fetch_message.assert_not_called()
        pinned.edit.assert_not_called()

    def test_image_not_recomposed_when_no_progress(self):
        """進捗 0 のプレイでは画像再合成も編集も走らない"""
        cog = _make_cog()
        task = make_task(type="level", set_value=2, value=99)  # マッチしない
        SessionManager.instance().start(_make_session([task]))
        interaction = make_mock_interaction()
        _attach_pinned_message(interaction)

        async def run() -> None:
            await _invoke_play(cog, interaction)

        asyncio.run(run())

        proc = cast(Any, cog)._image_processor
        proc.compose.assert_not_called()
        interaction.channel.fetch_message.assert_not_called()

    def test_compose_failure_logged_but_response_continues(self):
        """画像合成失敗時も embed の followup は送られる (握りつぶさず警告)"""
        cog = _make_cog()
        task = make_task(type="level", set_value=1, value=5)
        SessionManager.instance().start(_make_session([task]))
        interaction = make_mock_interaction()
        _attach_pinned_message(interaction)
        # compose を意図的に失敗させる
        proc = cast(Any, cog)._image_processor
        proc.compose = MagicMock(
            side_effect=FileNotFoundError("画像ファイルが見つかりません")
        )

        async def run() -> None:
            await _invoke_play(cog, interaction)

        # 例外が伝播しない
        asyncio.run(run())

        # message.edit は呼ばれない (compose 失敗時にスキップ)
        interaction.channel.fetch_message.assert_not_called()
        # embed は依然送信される
        interaction.followup.send.assert_awaited_once()

    def test_message_edit_failure_logged_but_response_continues(self):
        """`message.edit` が DiscordException で失敗しても embed の followup は送られる"""
        cog = _make_cog()
        task = make_task(type="level", set_value=1, value=5)
        SessionManager.instance().start(_make_session([task]))
        interaction = make_mock_interaction()
        pinned = _attach_pinned_message(interaction)
        pinned.edit = AsyncMock(
            side_effect=discord.HTTPException(MagicMock(), "boom")
        )

        async def run() -> None:
            await _invoke_play(cog, interaction)

        # 例外が伝播しない
        asyncio.run(run())

        # message.edit は試行された
        pinned.edit.assert_awaited_once()
        # embed は依然送信される
        interaction.followup.send.assert_awaited_once()


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
        # cog インスタンスにバインドされた autocomplete callback を直接呼ぶ
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
