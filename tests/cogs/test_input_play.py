"""
src/cogs/input_play.py のユニットテスト

`/play` コマンドの主な振る舞いを検証します:

* charming / combo の自然数バリデーション (ephemeral 拒否、副作用なし)
* 進行中セッションが無い場合は ephemeral でエラー応答
* `SongRepository` に存在しない楽曲名は ephemeral でエラー応答
* Happy Path: `PlayRecord` がセッションに追加され、タスク評価結果が embed で返る
* 進捗があった場合は ``current`` / ``set_value`` が embed に反映される
* 進捗があったらピン留めメッセージの embed fields がセッションタスクで再構築される
* 新規 cleared が発生したら合わせてピン留めメッセージの添付画像も差し替えられる
* 新規 cleared が無い (進捗のみ) ときは画像再合成は走らず embed のみ更新される
* 進捗自体が無いときは画像合成もメッセージ編集も走らない
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
    interaction: MagicMock,
    *,
    message_id: int = 999_111,
    initial_embed: Optional[discord.Embed] = None,
) -> MagicMock:
    """
    `interaction.channel.fetch_message` をピン留めメッセージ風 mock に差し替える

    `_rebuild_embed_with_tasks` が `message.embeds[0]` をコピー元にするため、
    既定で title / description / footer / image を備えた embed を 1 件保持させる。
    呼び出し側で挙動を変えたい場合は ``initial_embed`` を上書き指定する。
    """
    pinned = MagicMock()
    pinned.id = message_id
    pinned.edit = AsyncMock()
    if initial_embed is None:
        initial_embed = discord.Embed(
            title="🎯 セッション開始",
            description="- パネル数: 1\n- モザイク: なし (block=300px)",
            color=discord.Color.blurple(),
        )
        initial_embed.set_image(url="attachment://panels.png")
        initial_embed.set_footer(
            text="制限時間: 30分 | /play でプレイ情報を送信 | /answer で回答"
        )
        # 既存お題 (古い current=0 状態) を field として 1 件持たせ、置換が起きることを
        # テスト側で観測できるようにする
        initial_embed.add_field(
            name="⬜ パネル 0 (0/1)", value="旧お題説明", inline=False
        )
    pinned.embeds = [initial_embed]
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

    def test_unknown_difficulty_returns_ephemeral_warning(self):
        """楽曲に存在しない難易度は ephemeral warning で拒否される"""
        # Easy のみを持つ楽曲 (Hard は存在しない)
        easy_only_song = Song(
            name="EasyOnlySong",
            shelf="A",
            book="B",
            version="v1",
            time=120,
            composer=["C"],
            levels={"Easy": 1},
            notes={"Easy": 50},
        )
        cog = _make_cog(songs=[easy_only_song])
        SessionManager.instance().start(
            _make_session(
                [make_task(type="level", set_value=1, value=5)],
                song_name="EasyOnlySong",
            )
        )
        interaction = make_mock_interaction()

        async def run() -> None:
            await _invoke_play(
                cog,
                interaction,
                song="EasyOnlySong",
                difficulty=app_commands.Choice(name="Hard", value="Hard"),
                charming=10,
                combo=10,
            )

        asyncio.run(run())

        interaction.response.send_message.assert_awaited_once()
        _, kwargs = interaction.response.send_message.call_args
        assert kwargs.get("ephemeral") is True
        # warning embed (orange)
        embed: discord.Embed = kwargs["embed"]
        assert embed.color == discord.Color.orange()
        assert embed.description is not None
        assert "Hard" in embed.description
        # defer / followup は呼ばれず PlayRecord は追加されない
        interaction.response.defer.assert_not_called()
        interaction.followup.send.assert_not_called()
        session = SessionManager.instance().current()
        assert session is not None
        assert session.play_records == []

    def test_charming_exceeds_notes_returns_ephemeral_warning(self):
        """charming がノーツ数を超える場合は ephemeral warning で拒否される"""
        # SampleSong の Hard は notes=200
        cog = _make_cog()
        SessionManager.instance().start(
            _make_session([make_task(type="level", set_value=1, value=5)])
        )
        interaction = make_mock_interaction()

        async def run() -> None:
            await _invoke_play(
                cog,
                interaction,
                song="SampleSong",
                difficulty=app_commands.Choice(name="Hard", value="Hard"),
                charming=201,  # ノーツ数 200 を 1 超過
                combo=100,
            )

        asyncio.run(run())

        interaction.response.send_message.assert_awaited_once()
        _, kwargs = interaction.response.send_message.call_args
        assert kwargs.get("ephemeral") is True
        embed: discord.Embed = kwargs["embed"]
        assert embed.color == discord.Color.orange()
        assert embed.description is not None
        assert "charming" in embed.description
        assert "200" in embed.description
        interaction.response.defer.assert_not_called()
        interaction.followup.send.assert_not_called()
        session = SessionManager.instance().current()
        assert session is not None
        assert session.play_records == []

    def test_combo_exceeds_notes_returns_ephemeral_warning(self):
        """combo がノーツ数を超える場合は ephemeral warning で拒否される"""
        cog = _make_cog()
        SessionManager.instance().start(
            _make_session([make_task(type="level", set_value=1, value=5)])
        )
        interaction = make_mock_interaction()

        async def run() -> None:
            await _invoke_play(
                cog,
                interaction,
                song="SampleSong",
                difficulty=app_commands.Choice(name="Hard", value="Hard"),
                charming=100,
                combo=201,  # ノーツ数 200 を 1 超過
            )

        asyncio.run(run())

        interaction.response.send_message.assert_awaited_once()
        _, kwargs = interaction.response.send_message.call_args
        assert kwargs.get("ephemeral") is True
        embed: discord.Embed = kwargs["embed"]
        assert embed.color == discord.Color.orange()
        assert embed.description is not None
        assert "combo" in embed.description
        assert "200" in embed.description
        interaction.response.defer.assert_not_called()
        interaction.followup.send.assert_not_called()
        session = SessionManager.instance().current()
        assert session is not None
        assert session.play_records == []

    def test_charming_equal_to_notes_passes(self):
        """charming / combo がノーツ数と一致 (フルコンボ) する場合は通過する"""
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
                charming=200,  # ノーツ数 200 と一致 → 許容
                combo=200,
            )

        asyncio.run(run())

        # defer されて PlayRecord が登録される
        interaction.response.defer.assert_awaited_once()
        session = SessionManager.instance().current()
        assert session is not None
        assert len(session.play_records) == 1


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
                charming=150,
                combo=180,
            )

        asyncio.run(run())

        session = SessionManager.instance().current()
        assert session is not None
        assert len(session.play_records) == 1
        rec: PlayRecord = session.play_records[0]
        assert rec.song_name == "SampleSong"
        assert rec.difficulty == "Hard"
        assert rec.charming == 150
        assert rec.combo == 180

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
            await _invoke_play(cog, interaction, charming=150, combo=180)

        asyncio.run(run())

        assert task.current == 0
        assert task.cleared is False
        # embed に「進捗のあったタスクはありません。」が含まれる
        _, kwargs = interaction.followup.send.call_args
        embed: discord.Embed = kwargs["embed"]
        assert embed.description is not None
        assert "進捗のあったタスクはありません" in embed.description
        # 進捗無しでも charming / combo は description に表示される
        assert "charming: 150" in embed.description
        assert "combo: 180" in embed.description

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

    def test_newly_cleared_task_uses_check_symbol_without_marker(self):
        """新規 cleared に到達したタスクは ✅ シンボルのみで識別され、追加マーカーは付かない"""
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
        # cleared 済みのため symbol は ✅、追加の "[クリア!]" 表記は付かない
        assert embed.fields[0].name is not None
        assert embed.fields[0].name.startswith("✅ パネル 0 (1/1)")
        assert "[クリア!]" not in embed.fields[0].name

    def test_play_info_in_description(self):
        """description に charming / combo が含まれる"""
        cog = _make_cog()
        task = make_task(type="level", set_value=1, value=5)
        SessionManager.instance().start(_make_session([task]))
        interaction = make_mock_interaction()
        _attach_pinned_message(interaction)

        async def run() -> None:
            # SampleSong の Hard 譜面はノーツ 200 のため、超過しない値を指定する
            await _invoke_play(cog, interaction, charming=123, combo=156)

        asyncio.run(run())

        _, kwargs = interaction.followup.send.call_args
        embed: discord.Embed = kwargs["embed"]
        assert embed.description is not None
        assert "charming: 123" in embed.description
        assert "combo: 156" in embed.description

    def test_already_cleared_task_is_omitted_from_embed(self):
        """プレイ前から cleared 済みのタスクは embed の field に含めない"""
        cog = _make_cog()
        # プレイ前から cleared 済みの level タスク
        # (set_value=1 / value=5 / current=2 → 既に cleared)。
        # 1 回プレイで Hard=5 にマッチし current が 2→3 と更新されるが、
        # プレイ前から cleared 済みのため embed には現れない想定。
        already_cleared = make_task(
            type="level",
            set_value=1,
            value=5,
            description_template="Lv.valueの譜面を持つ楽曲をset回play",
            play_quality="プレイ",
            current=2,
            cleared=True,
        )
        # 比較用: 未クリアで進捗が乗る別のタスク (level=5 マッチ系 / set=2)
        progressing = make_task(
            type="level",
            set_value=2,
            value=5,
            description_template="Lv.valueの譜面を持つ楽曲をset回play",
            play_quality="プレイ",
        )
        SessionManager.instance().start(
            _make_session([already_cleared, progressing])
        )
        interaction = make_mock_interaction()
        _attach_pinned_message(interaction)

        async def run() -> None:
            await _invoke_play(cog, interaction)

        asyncio.run(run())

        # cleared 済みでも内部状態 (current) は更新される
        assert already_cleared.current == 3
        assert already_cleared.cleared is True
        # 一方で embed の field には現れない (もう一つの進捗 task のみが表示される)
        _, kwargs = interaction.followup.send.call_args
        embed: discord.Embed = kwargs["embed"]
        assert len(embed.fields) == 1
        assert embed.fields[0].name is not None
        assert embed.fields[0].name.startswith("⬜ パネル 1 (1/2)")


# ==================================================
# ピン留めメッセージの再構築 (embed fields + 任意で画像)
# ==================================================
class TestPinnedMessageRefresh:
    """進捗発生 → embed fields 再構築 / 新規 cleared 時は画像再合成も伴うことを検証する"""

    def test_image_recomposed_and_embed_refreshed_when_new_clear(self):
        """新規 cleared が起きたら compose + message.edit (embed + attachments) が呼ばれる"""
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
        interaction.channel.fetch_message.assert_awaited_once_with(999_111)
        pinned.edit.assert_awaited_once()
        _, edit_kwargs = pinned.edit.call_args
        # 添付画像が差し替えられる
        attachments = edit_kwargs.get("attachments")
        assert attachments is not None and len(attachments) == 1
        assert isinstance(attachments[0], discord.File)
        # embed も同送される (fields は cleared 後の状態に再構築)
        new_embed: discord.Embed = edit_kwargs["embed"]
        assert len(new_embed.fields) == 1
        assert new_embed.fields[0].name is not None
        assert new_embed.fields[0].name.startswith("✅ パネル 0 (1/1)")

    def test_embed_refreshed_but_image_skipped_when_no_new_clear(self):
        """進捗のみ (cleared に到達せず) では画像は再合成されず embed のみ更新される"""
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
        # compose は呼ばれない (画像差し替え不要)
        proc = cast(Any, cog)._image_processor
        proc.compose.assert_not_called()
        # メッセージ取得 + embed 更新は走る
        interaction.channel.fetch_message.assert_awaited_once_with(999_111)
        pinned.edit.assert_awaited_once()
        _, edit_kwargs = pinned.edit.call_args
        # attachments は付与されない (embed のみ更新)
        assert "attachments" not in edit_kwargs
        new_embed: discord.Embed = edit_kwargs["embed"]
        # fields は最新進捗 (1/3) で再構築される
        assert len(new_embed.fields) == 1
        assert new_embed.fields[0].name is not None
        assert new_embed.fields[0].name.startswith("⬜ パネル 0 (1/3)")

    def test_no_message_update_when_no_progress(self):
        """進捗 0 のプレイでは画像合成もメッセージ取得・編集も走らない"""
        cog = _make_cog()
        task = make_task(type="level", set_value=2, value=99)  # マッチしない
        SessionManager.instance().start(_make_session([task]))
        interaction = make_mock_interaction()
        pinned = _attach_pinned_message(interaction)

        async def run() -> None:
            await _invoke_play(cog, interaction)

        asyncio.run(run())

        proc = cast(Any, cog)._image_processor
        proc.compose.assert_not_called()
        interaction.channel.fetch_message.assert_not_called()
        pinned.edit.assert_not_called()

    def test_embed_fields_match_all_session_tasks(self):
        """embed fields は進捗の有無に関わらず session.tasks 全件で再構築される"""
        cog = _make_cog()
        # 1 件は新規 cleared、もう 1 件はマッチせず据え置き
        match_task = make_task(
            type="level",
            set_value=1,
            value=5,
            description_template="Lv.valueの譜面をset回play",
            play_quality="プレイ",
        )
        no_match_task = make_task(
            type="level",
            set_value=2,
            value=99,
            description_template="Lv.valueの譜面をset回play",
            play_quality="プレイ",
        )
        SessionManager.instance().start(
            _make_session([match_task, no_match_task])
        )
        interaction = make_mock_interaction()
        pinned = _attach_pinned_message(interaction)

        async def run() -> None:
            await _invoke_play(cog, interaction)

        asyncio.run(run())

        pinned.edit.assert_awaited_once()
        _, edit_kwargs = pinned.edit.call_args
        new_embed: discord.Embed = edit_kwargs["embed"]
        # 全タスクが field として並ぶ (進捗のあったものだけではない)
        assert len(new_embed.fields) == 2
        assert new_embed.fields[0].name is not None
        assert new_embed.fields[0].name.startswith("✅ パネル 0 (1/1)")
        assert new_embed.fields[1].name is not None
        assert new_embed.fields[1].name.startswith("⬜ パネル 1 (0/2)")

    def test_embed_metadata_preserved_after_refresh(self):
        """既存 embed の title / description / footer / color / image は保持される"""
        cog = _make_cog()
        task = make_task(type="level", set_value=3, value=5)  # 進捗のみ (新規 cleared 無し)
        SessionManager.instance().start(_make_session([task]))
        interaction = make_mock_interaction()
        # メタ情報を持つカスタム embed を差し込み、保持されることを観測する
        custom = discord.Embed(
            title="🎯 セッション開始",
            description="- パネル数: 4\n- モザイク: 強 (block=45px)",
            color=discord.Color.blurple(),
        )
        custom.set_image(url="attachment://panels.png")
        custom.set_footer(text="制限時間: 30分 | /play | /answer")
        custom.add_field(name="旧 field", value="旧 value", inline=False)
        pinned = _attach_pinned_message(interaction, initial_embed=custom)

        async def run() -> None:
            await _invoke_play(cog, interaction)

        asyncio.run(run())

        pinned.edit.assert_awaited_once()
        _, edit_kwargs = pinned.edit.call_args
        new_embed: discord.Embed = edit_kwargs["embed"]
        assert new_embed.title == "🎯 セッション開始"
        assert new_embed.description == (
            "- パネル数: 4\n- モザイク: 強 (block=45px)"
        )
        assert new_embed.color == discord.Color.blurple()
        assert new_embed.image.url == "attachment://panels.png"
        assert new_embed.footer.text == "制限時間: 30分 | /play | /answer"
        # 旧 field は置換されている
        assert len(new_embed.fields) == 1
        assert new_embed.fields[0].name is not None
        assert "旧 field" not in new_embed.fields[0].name

    def test_compose_failure_still_updates_embed(self):
        """画像合成失敗時も embed の更新は続行され、followup も送られる"""
        cog = _make_cog()
        task = make_task(type="level", set_value=1, value=5)
        SessionManager.instance().start(_make_session([task]))
        interaction = make_mock_interaction()
        pinned = _attach_pinned_message(interaction)
        # compose を意図的に失敗させる
        proc = cast(Any, cog)._image_processor
        proc.compose = MagicMock(
            side_effect=FileNotFoundError("画像ファイルが見つかりません")
        )

        async def run() -> None:
            await _invoke_play(cog, interaction)

        # 例外が伝播しない
        asyncio.run(run())

        # 画像差し替えは失敗するが embed 更新は続行される
        interaction.channel.fetch_message.assert_awaited_once_with(999_111)
        pinned.edit.assert_awaited_once()
        _, edit_kwargs = pinned.edit.call_args
        assert "attachments" not in edit_kwargs  # compose 失敗で添付は付かない
        assert isinstance(edit_kwargs.get("embed"), discord.Embed)
        # embed の followup は依然送信される
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
