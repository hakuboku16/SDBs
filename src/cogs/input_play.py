"""
/play スラッシュコマンドを定義するモジュール

ARCHITECTURE.md ステップ 5.6 に従い、プレイ結果を入力してタスク進捗を更新する処理を提供します:

1. 引数 (`song` / `difficulty` / `charming` / `combo`) を受け取り、`is_natural_number`
   で charming / combo を検証する
2. 進行中セッションが無ければ ephemeral でエラー応答 (副作用なし)
3. `PlayRecord` を生成しセッションへ追加
4. 全 `Task` を `TaskEvaluator` で評価し、進捗のあったタスクと新たに cleared
   になったタスクを集計
5. 進捗があった場合は `Session.pinned_message_id` のメッセージを編集して
   embed の fields をセッションの現在タスクで再構築する。新規 cleared が発生した
   ときは合わせて `ImageProcessor.compose` でパネル画像も再合成し、添付を差し替える
6. 進捗結果を embed としてチャンネルへ公開応答する

楽曲名のオートコンプリートは `/answer` と共通化された [src/cogs/_helpers.py](src/cogs/_helpers.py) の
`build_song_autocomplete` を利用します。`SongRepository` をクロージャに閉じ込んだ
async 関数を `play.autocomplete("song")` 経由で登録するため、cog インスタンス生成時に
バインドが完了している必要があります。
"""

import logging
from io import BytesIO
from typing import Any, Optional

import discord
from discord import app_commands
from discord.ext import commands

from src.cogs._helpers import (
    SongAutocomplete,
    build_error_embed,
    build_song_autocomplete,
    build_topic_field,
    build_warning_embed,
)
from src.core.config import get_assets_config
from src.services.image_processor import ImageProcessor
from src.services.session import PlayRecord, Session
from src.services.session_manager import SessionManager
from src.services.song_repository import SongRepository
from src.services.task import Task
from src.services.task_evaluator import TaskEvaluator
from src.utils.validators import is_natural_number

# モジュールスコープのロガー (production では `__main__` 親ロガーから propagate)
logger = logging.getLogger(__name__)


# ==================================================
# 静的選択肢 / 定数
# ==================================================
# 難易度: assets/data/all_topics.json の "difficult" / 楽曲メタの levels キーと同期
_DIFFICULTY_CHOICES: list[app_commands.Choice[str]] = [
    app_commands.Choice(name="Easy", value="Easy"),
    app_commands.Choice(name="Normal", value="Normal"),
    app_commands.Choice(name="Hard", value="Hard"),
    app_commands.Choice(name="Extra", value="Extra"),
]

# `/start` で添付したパネル画像と同じファイル名を使い、メッセージ編集時に視覚的にも一貫させる
_PANEL_IMAGE_FILENAME: str = "panels.png"

# /play 応答 embed の色 (進捗を緑系で示す)
_EMBED_COLOR: discord.Color = discord.Color.green()

# 進捗のあったタスクが無い場合に description として表示する文言
_NO_PROGRESS_DESCRIPTION: str = "進捗のあったタスクはありません。"


# ==================================================
# /play cog
# ==================================================
class InputPlayCog(commands.Cog):
    """
    `/play` スラッシュコマンドを提供する cog

    依存はコンストラクタで注入し、テスト時は mock を差し込めるようにします。
    `setup()` 関数が `Config` 経由で実装の依存を構築し、Bot に登録します。
    """

    def __init__(
        self,
        bot: commands.Bot,
        *,
        song_repository: SongRepository,
        task_evaluator: TaskEvaluator,
        image_processor: ImageProcessor,
    ) -> None:
        """
        cog を初期化する

        Args:
            bot: 親 Bot インスタンス (`SDBsBot` を想定)
            song_repository: 楽曲リポジトリ (オートコンプリート / 楽曲存在チェックに使用)
            task_evaluator: タスク評価戦略 (type ごとの評価関数を保持)
            image_processor: 画像プロセッサ (パネル画像の再合成に使用)
        """
        super().__init__()
        self.bot: commands.Bot = bot
        self._song_repository: SongRepository = song_repository
        self._task_evaluator: TaskEvaluator = task_evaluator
        self._image_processor: ImageProcessor = image_processor
        # `_helpers.build_song_autocomplete` で `SongRepository` をクロージャに閉じ込んだ
        # 関数を作り、後段の `play_song_autocomplete` メソッドから委譲する。
        self._song_autocomplete: SongAutocomplete = build_song_autocomplete(
            song_repository
        )

    # --------------------------------------------------
    # スラッシュコマンド本体
    # --------------------------------------------------
    @app_commands.command(
        name="play",
        description="プレイした楽曲情報を入力します",
    )
    @app_commands.describe(
        song="プレイした楽曲名 (部分一致で候補表示)",
        difficulty="プレイした難易度",
        charming="リザルト画面の charming 数 (1 以上の自然数)",
        combo="リザルト画面の combo 数 (1 以上の自然数)",
    )
    @app_commands.choices(difficulty=_DIFFICULTY_CHOICES)
    async def play(
        self,
        interaction: discord.Interaction,
        song: str,
        difficulty: app_commands.Choice[str],
        charming: int,
        combo: int,
    ) -> None:
        """
        プレイ結果を 1 件入力し、タスクを評価して進捗を更新する

        - 早期失敗パス (バリデーション / セッション無し / 楽曲未知) は ephemeral で応答
        - 成功パスは defer で公開応答に切り替え、followup で embed を送信
        """
        # ----- 1) 引数バリデーション (charming / combo) -----
        if not is_natural_number(charming):
            await interaction.response.send_message(
                embed=build_error_embed(
                    f"charming は 1 以上の自然数で指定してください: {charming}"
                ),
                ephemeral=True,
            )
            return
        if not is_natural_number(combo):
            await interaction.response.send_message(
                embed=build_error_embed(
                    f"combo は 1 以上の自然数で指定してください: {combo}"
                ),
                ephemeral=True,
            )
            return

        # ----- 2) 進行中セッションの確認 -----
        manager: SessionManager = SessionManager.instance()
        session: Optional[Session] = manager.current()
        if session is None:
            await interaction.response.send_message(
                embed=build_error_embed(
                    "進行中のセッションがありません。/start で新しいセッションを開始してください。"
                ),
                ephemeral=True,
            )
            return

        # ----- 3) 楽曲存在チェック (autocomplete を経由しない手入力に備える) -----
        song_meta = self._song_repository.find_by_name(song)
        if song_meta is None:
            await interaction.response.send_message(
                embed=build_error_embed(f"指定された楽曲が見つかりません: {song}"),
                ephemeral=True,
            )
            return

        # ----- 3.5) 難易度・charming / combo 上限チェック -----
        # 楽曲メタの notes 辞書から難易度キーを引き、ノーツ数を上限として
        # charming / combo を検証する。逸脱時は ephemeral の warning で応答し、
        # PlayRecord 追加・タスク評価は行わない。
        notes_count: Optional[int] = song_meta.notes.get(difficulty.value)
        if notes_count is None:
            await interaction.response.send_message(
                embed=build_warning_embed(
                    f"楽曲 '{song}' には難易度 {difficulty.value} の譜面がありません。"
                ),
                ephemeral=True,
            )
            return
        if charming > notes_count:
            await interaction.response.send_message(
                embed=build_warning_embed(
                    f"charming ({charming}) が楽曲 '{song}' の {difficulty.value} 譜面の"
                    f"ノーツ数 ({notes_count}) を超えています。"
                ),
                ephemeral=True,
            )
            return
        if combo > notes_count:
            await interaction.response.send_message(
                embed=build_warning_embed(
                    f"combo ({combo}) が楽曲 '{song}' の {difficulty.value} 譜面の"
                    f"ノーツ数 ({notes_count}) を超えています。"
                ),
                ephemeral=True,
            )
            return

        # ----- 4) 画像再合成・メッセージ編集を含むため defer -----
        await interaction.response.defer()

        # ----- 5) PlayRecord 構築・登録 -----
        record: PlayRecord = PlayRecord(
            song_name=song,
            difficulty=difficulty.value,
            charming=charming,
            combo=combo,
        )
        session.add_play(record)

        # ----- 6) 全タスク評価 -----
        progressed: list[tuple[int, Task, bool]] = self._evaluate_tasks(
            session=session, record=record
        )

        # ----- 7) 進捗があればピン留めメッセージを更新 -----
        # - embed の fields は進捗 (current 増加) がある限り常に最新化する。
        # - パネル画像の再合成は新規 cleared が発生したときのみ行う
        #   (cleared_indices が変化しない場合は同じ画像が出力されるため)。
        if progressed:
            needs_image_refresh: bool = any(newly for _, _, newly in progressed)
            await self._refresh_pinned_message(
                interaction, session, refresh_image=needs_image_refresh
            )

        # ----- 8) 進捗 embed を返す -----
        embed: discord.Embed = self._build_progress_embed(
            record=record, progressed=progressed
        )
        await interaction.followup.send(embed=embed)

    # --------------------------------------------------
    # オートコンプリート (instance method 形式で登録)
    # --------------------------------------------------
    @play.autocomplete("song")
    async def _song_autocomplete_callback(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """
        楽曲名オートコンプリート

        `_helpers.build_song_autocomplete` で生成した関数へ委譲する薄いラッパ。
        cog インスタンスメソッドとして登録するため `self` を受け取る形式が必須。
        """
        return await self._song_autocomplete(interaction, current)

    # --------------------------------------------------
    # 内部ヘルパー: タスク評価
    # --------------------------------------------------
    def _evaluate_tasks(
        self,
        *,
        session: Session,
        record: PlayRecord,
    ) -> list[tuple[int, Task, bool]]:
        """
        現セッションの全タスクを評価し、進捗のあったタスクのリストを返す

        `TaskEvaluator.evaluate` が返した新しい ``current`` 値が現在値より大きい場合のみ
        ``Task.set_progress`` で反映し、戻り値 (新規 cleared 判定) と合わせて記録する。

        累積系タスク (例: `level_total`) は既に cleared 状態でも ``current`` が増加し
        うるため、状態更新は常に行うが、表示用の戻り値からは「プレイ前から cleared
        だったタスク」を除外する (要件: すでに達成したお題は embed から省略)。

        Args:
            session: 進行中セッション
            record: 直近に追加された `PlayRecord`

        Returns:
            ``(タスクの 0-origin index, 更新後 Task, 新規 cleared 判定)`` のリスト
            (進捗のなかったタスク / プレイ前から cleared だったタスクは含まない)
        """
        progressed: list[tuple[int, Task, bool]] = []
        for index, task in enumerate(session.tasks):
            try:
                new_current: int = self._task_evaluator.evaluate(
                    task,
                    record,
                    session.play_records,
                    self._song_repository,
                )
            except ValueError as e:
                # 未対応 type / 楽曲メタ欠落等は致命的ではないため警告ログのみで継続
                logger.warning("タスク評価に失敗しました (type=%s): %s", task.type, e)
                continue
            if new_current > task.current:
                # プレイ前のクリア状態を退避してから状態更新する。
                # 状態 (current) は累積整合性のため常に更新するが、
                # プレイ前から cleared 済みのタスクは embed から省略する。
                was_cleared: bool = task.cleared
                newly_cleared: bool = task.set_progress(new_current)
                if was_cleared:
                    continue
                progressed.append((index, task, newly_cleared))
        return progressed

    # --------------------------------------------------
    # 内部ヘルパー: ピン留めメッセージの再構築 (embed fields + 任意で画像)
    # --------------------------------------------------
    async def _refresh_pinned_message(
        self,
        interaction: discord.Interaction,
        session: Session,
        *,
        refresh_image: bool,
    ) -> None:
        """
        ピン留めされたタスク提示メッセージを最新の進捗状態に同期する

        - embed の fields をセッションの現在タスクから再構築し、進捗値 (current /
          set_value) と cleared シンボルを最新化する。title / description / footer /
          color / image (`attachment://panels.png`) は既存 embed から保持するため、
          `/start` 時の体裁は崩れない。
        - ``refresh_image=True`` のときはパネル画像も再合成して attachments に差し
          替える (新規 cleared が発生した場合の想定)。

        画像合成失敗時も embed の更新は試みる (要件「進捗があれば常に更新」)。
        失敗 (画像合成エラー / メッセージ取得失敗 / 編集失敗) は warning ログに残し、
        `/play` 自体の応答は継続する (要件「エラーは握りつぶさず意味のあるメッセージ付きで処理」)。
        """
        if session.pinned_message_id is None:
            # `/start` が完了していれば必ず設定されているはずだが、防衛的に no-op
            logger.warning(
                "pinned_message_id が未設定のためメッセージ更新をスキップします"
            )
            return

        # ----- 画像が必要なら先に合成 (失敗しても embed 更新は続行) -----
        composed_image: Optional[BytesIO] = None
        if refresh_image:
            try:
                composed_image = self._image_processor.compose(
                    song_name=session.song_name,
                    panel_count=session.panel_count,
                    cleared_indices=session.cleared_panel_indices(),
                    rotation_angle=session.rotation_angle,
                    grayscale=session.grayscale,
                    mosaic_block=session.mosaic_block,
                )
            except (FileNotFoundError, ValueError) as e:
                logger.warning("/play でのパネル画像再合成に失敗しました: %s", e)

        # ----- チャンネルナロー -----
        # interaction.channel は CategoryChannel / ForumChannel (非 Messageable) も
        # 含む union 型のため、Messageable へナローしてから fetch_message を呼ぶ。
        channel = interaction.channel
        if channel is None:
            logger.warning(
                "interaction.channel が None のためピン留めメッセージを更新できません"
            )
            return
        if not isinstance(channel, discord.abc.Messageable):
            logger.warning(
                "チャンネル (type=%s) は Messageable ではないため"
                "メッセージ更新をスキップします",
                type(channel).__name__,
            )
            return

        # ----- メッセージ取得 + embed/添付差し替え -----
        try:
            message = await channel.fetch_message(session.pinned_message_id)
            new_embed: Optional[discord.Embed] = self._rebuild_embed_with_tasks(
                message, session
            )
            edit_kwargs: dict[str, Any] = {}
            if new_embed is not None:
                edit_kwargs["embed"] = new_embed
            if composed_image is not None:
                # attachments を新しい File 1 件で上書き → 既存添付を差し替える
                file = discord.File(composed_image, filename=_PANEL_IMAGE_FILENAME)
                edit_kwargs["attachments"] = [file]
                # 既存 embed の image.url は送信後に Discord 側で CDN URL に解決済み
                # のため、attachments を差し替えるだけでは embed が削除済み
                # attachment を指したままとなり、新画像が embed ではなく
                # メッセージ末尾の別添付として表示されてしまう。
                # `attachment://` スキームで再バインドし、新 attachment に
                # 解決し直させる必要がある。
                if new_embed is not None:
                    new_embed.set_image(url=f"attachment://{_PANEL_IMAGE_FILENAME}")
            if not edit_kwargs:
                # embed 不在 + 画像合成失敗の二重落ちでは更新素材がないため no-op
                logger.warning(
                    "更新素材が無いためピン留めメッセージ編集をスキップします"
                    " (message_id=%s)",
                    session.pinned_message_id,
                )
                return
            await message.edit(**edit_kwargs)
        except discord.DiscordException as e:
            logger.warning(
                "ピン留めメッセージの更新に失敗しました (message_id=%s): %s",
                session.pinned_message_id,
                e,
            )

    # --------------------------------------------------
    # 内部ヘルパー: 既存 embed を複製し fields のみ最新化
    # --------------------------------------------------
    @staticmethod
    def _rebuild_embed_with_tasks(
        message: discord.Message,
        session: Session,
    ) -> Optional[discord.Embed]:
        """
        ピン留めメッセージの既存 embed を複製し、fields のみセッションの現在タスクで
        置き換えた新 embed を返す

        - title / description / footer / color / image (添付参照) は既存値を保持する
        - fields は `build_topic_field` で 1 タスク 1 field に整形し直す
          (`/start` `/progress` と同形式)

        Args:
            message: ピン留め元のメッセージ (embed のコピー元)
            session: 現在進行中のセッション (タスク状態のソース)

        Returns:
            複製後の `discord.Embed`。``message.embeds`` が空のときは ``None``
            (呼び出し側で fallback を行う)
        """
        if not message.embeds:
            return None
        new_embed: discord.Embed = message.embeds[0].copy()
        new_embed.clear_fields()
        for index, task in enumerate(session.tasks):
            name, value = build_topic_field(index, task)
            new_embed.add_field(name=name, value=value, inline=False)
        return new_embed

    # --------------------------------------------------
    # 内部ヘルパー: 進捗 embed 構築
    # --------------------------------------------------
    @staticmethod
    def _build_progress_embed(
        *,
        record: PlayRecord,
        progressed: list[tuple[int, Task, bool]],
    ) -> discord.Embed:
        """
        進捗のあったタスクを列挙する embed を組み立てる

        - ``description`` に入力された charming / combo を常に表示する。
          進捗のあったタスクが無い場合は続けて「進捗のあったタスクはありません。」
          を併記する。
        - 進捗があった場合は 1 タスク 1 field でパネル番号 / 進捗 / お題内容を表示する。
          field の整形は `build_topic_field` に集約 (`/start` `/progress` と同形式)。
          新規 cleared 判定は ``✅`` シンボルで識別可能なため、追加の文字マーカーは
          付与しない。

        Args:
            record: 入力された `PlayRecord` (タイトル / description 表示に利用)
            progressed: ``_evaluate_tasks`` の戻り値 (プレイ前から cleared 済みの
                タスクは既に除外されている)

        Returns:
            進捗まとめ embed
        """
        title: str = f"▶ プレイ記録を追加: {record.song_name} ({record.difficulty})"
        play_info: str = f"♪ charming: {record.charming} / combo: {record.combo}"
        description: str = (
            f"{play_info}\n{_NO_PROGRESS_DESCRIPTION}" if not progressed else play_info
        )
        embed = discord.Embed(
            title=title,
            description=description,
            color=_EMBED_COLOR,
        )
        for index, task, _ in progressed:
            name, value = build_topic_field(index, task)
            embed.add_field(name=name, value=value, inline=False)
        return embed


# ==================================================
# extension エントリポイント
# ==================================================
async def setup(bot: commands.Bot) -> None:
    """
    `Bot.load_extension` から呼ばれる cog 登録関数

    実行時の依存 (リポジトリ / 評価器 / 画像プロセッサ) を構築して cog に注入します。
    """
    assets = get_assets_config()
    song_repository = SongRepository(
        songs_json=assets.songs_json,
        images_dir=assets.images_dir,
    )
    task_evaluator = TaskEvaluator()
    image_processor = ImageProcessor(song_repository=song_repository)

    cog = InputPlayCog(
        bot,
        song_repository=song_repository,
        task_evaluator=task_evaluator,
        image_processor=image_processor,
    )
    await bot.add_cog(cog)
