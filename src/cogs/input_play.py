"""
/play スラッシュコマンドを定義するモジュール

ARCHITECTURE.md ステップ 5.6 に従い、プレイ結果を入力してタスク進捗を更新する処理を提供します:

1. 引数 (`song` / `difficulty` / `charming` / `combo`) を受け取り、`is_natural_number`
   で charming / combo を検証する
2. 進行中セッションが無ければ ephemeral でエラー応答 (副作用なし)
3. `PlayRecord` を生成しセッションへ追加
4. 全 `Task` を `TaskEvaluator` で評価し、進捗のあったタスクと新たに cleared
   になったタスクを集計
5. 新たに cleared パネルがある場合は `ImageProcessor.compose` で画像を再合成し、
   `Session.pinned_message_id` のメッセージを編集して添付画像を差し替える
6. 進捗結果を embed としてチャンネルへ公開応答する

楽曲名のオートコンプリートは `/answer` と共通化された [src/cogs/_helpers.py](src/cogs/_helpers.py) の
`build_song_autocomplete` を利用します。`SongRepository` をクロージャに閉じ込んだ
async 関数を `play.autocomplete("song")` 経由で登録するため、cog インスタンス生成時に
バインドが完了している必要があります。
"""

import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from src.cogs._helpers import (
    SongAutocomplete,
    build_error_embed,
    build_song_autocomplete,
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

# embed.description の上限 (Discord 仕様 4096)。長大なお題列で溢れる事故を避ける
_DESCRIPTION_LIMIT: int = 4000


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
        if self._song_repository.find_by_name(song) is None:
            await interaction.response.send_message(
                embed=build_error_embed(
                    f"指定された楽曲が見つかりません: {song}"
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

        # ----- 7) 新規 cleared があればパネル画像を再合成し、ピン留めメッセージを編集 -----
        if any(newly for _, _, newly in progressed):
            await self._refresh_pinned_image(interaction, session)

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

        Args:
            session: 進行中セッション
            record: 直近に追加された `PlayRecord`

        Returns:
            ``(タスクの 0-origin index, 更新後 Task, 新規 cleared 判定)`` のリスト
            (進捗のなかったタスクは含まない)
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
                logger.warning(
                    "タスク評価に失敗しました (type=%s): %s", task.type, e
                )
                continue
            if new_current > task.current:
                newly_cleared: bool = task.set_progress(new_current)
                progressed.append((index, task, newly_cleared))
        return progressed

    # --------------------------------------------------
    # 内部ヘルパー: パネル画像再合成 + メッセージ編集
    # --------------------------------------------------
    async def _refresh_pinned_image(
        self,
        interaction: discord.Interaction,
        session: Session,
    ) -> None:
        """
        ピン留めされたタスク提示メッセージの添付画像を最新のクリア状況で差し替える

        失敗 (画像合成エラー / メッセージ取得失敗 / 編集失敗) は warning ログに残し、
        `/play` 自体の応答は継続する (要件「エラーは握りつぶさず意味のあるメッセージ付きで処理」)。
        """
        if session.pinned_message_id is None:
            # `/start` が完了していれば必ず設定されているはずだが、防衛的に no-op
            logger.warning(
                "pinned_message_id が未設定のため画像差し替えをスキップします"
            )
            return

        # ----- 画像合成 -----
        try:
            buffer = self._image_processor.compose(
                song_name=session.song_name,
                panel_count=session.panel_count,
                cleared_indices=session.cleared_panel_indices(),
                rotate=session.rotate,
                grayscale=session.grayscale,
                mosaic_block=session.mosaic_block,
            )
        except (FileNotFoundError, ValueError) as e:
            logger.warning("/play でのパネル画像再合成に失敗しました: %s", e)
            return

        # ----- メッセージ編集 -----
        channel = interaction.channel
        if channel is None:
            logger.warning(
                "interaction.channel が None のためピン留めメッセージを更新できません"
            )
            return
        fetch = getattr(channel, "fetch_message", None)
        if not callable(fetch):
            # DM など fetch_message を持たないチャンネルでは何もしない
            logger.warning(
                "チャンネル (type=%s) は fetch_message をサポートしていないため"
                "画像更新をスキップします",
                type(channel).__name__,
            )
            return

        try:
            message = await fetch(session.pinned_message_id)
            file = discord.File(buffer, filename=_PANEL_IMAGE_FILENAME)
            # attachments を新しい File 1 件で上書き → 既存添付を差し替える
            await message.edit(attachments=[file])
        except discord.DiscordException as e:
            logger.warning(
                "ピン留めメッセージの画像差し替えに失敗しました (message_id=%s): %s",
                session.pinned_message_id,
                e,
            )

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

        - 進捗のないプレイは ``description`` に「進捗のあったタスクはありません。」
        - 進捗があった場合は 1 行 1 タスクで ``current/set_value`` と新規 cleared フラグを表示

        Args:
            record: 入力された `PlayRecord` (タイトル表示に利用)
            progressed: ``_evaluate_tasks`` の戻り値

        Returns:
            進捗まとめ embed
        """
        title: str = (
            f"プレイ記録を追加: {record.song_name} ({record.difficulty})"
        )

        if not progressed:
            description: str = "進捗のあったタスクはありません。"
        else:
            lines: list[str] = []
            for index, task, newly_cleared in progressed:
                marker: str = " [クリア!]" if newly_cleared else ""
                value_part: str = (
                    f" ({task.value})" if task.value is not None else ""
                )
                lines.append(
                    f"{index + 1}. {task.type}{value_part}: "
                    f"{task.current}/{task.set_value}{marker}"
                )
            description = "\n".join(lines)
            if len(description) > _DESCRIPTION_LIMIT:
                description = description[: _DESCRIPTION_LIMIT - 1] + "…"

        return discord.Embed(
            title=title,
            description=description,
            color=_EMBED_COLOR,
        )


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
