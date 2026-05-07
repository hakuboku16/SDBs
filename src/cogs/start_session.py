"""
/start スラッシュコマンドを定義するモジュール

ARCHITECTURE.md ステップ 5.2 に従い、新しいセッションを開始する処理を提供します:

1. 引数 (`panels` / `rotate` / `grayscale` / `mosaic`) を受け取り設定値で検証
2. 既存セッションがあれば ephemeral で拒否 (要件: 同時 1 セッションのみ)
3. 楽曲をランダムに 1 件選び、`TaskGenerator` で N 個のお題を生成
4. `ImageProcessor.compose` で初期画像 (全パネル未開放) を合成
5. チャンネルへ投稿してピン留めし、メッセージ ID を `Session.pinned_message_id` に保持
6. `SessionManager.start` で「残り時間警告」「自動終了」用のタイマーを起動

タイマー満了時の振る舞いは本モジュール内のクロージャで完結させます
(`on_warning` でチャンネル通知 / `on_timeout` で `/end` と同等処理)。
ステップ 5.3 で `/end` cog を実装する際にロジックを共有化することを想定しています。
"""

import logging
import random
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from src.core.config import (
    DiscordConfig,
    SessionConfig,
    get_assets_config,
    get_discord_config,
    get_session_config,
)
from src.services.image_processor import ImageProcessor
from src.services.session import Session
from src.services.session_finalizer import SessionFinalizer
from src.services.session_manager import SessionManager
from src.services.song_repository import SongRepository
from src.services.task_generator import TaskGenerator

# モジュールスコープのロガー (production では `__main__` 親ロガーから propagate)
logger = logging.getLogger(__name__)


# ==================================================
# 静的選択肢 (app_commands.choices はリテラルでなければならないため module 定数で保持)
# ==================================================
# パネル数: SessionConfig.allowed_panel_counts と同期 (両方を変更する必要あり)
_PANEL_CHOICES: list[app_commands.Choice[int]] = [
    app_commands.Choice(name="4", value=4),
    app_commands.Choice(name="9", value=9),
    app_commands.Choice(name="16", value=16),
    app_commands.Choice(name="25", value=25),
]
# モザイクラベル: SessionConfig.mosaic_levels のキーと同期
_MOSAIC_CHOICES: list[app_commands.Choice[str]] = [
    app_commands.Choice(name="なし", value="なし"),
    app_commands.Choice(name="弱", value="弱"),
    app_commands.Choice(name="中", value="中"),
    app_commands.Choice(name="強", value="強"),
    app_commands.Choice(name="最強", value="最強"),
]

# 添付画像のファイル名 (ピン留めメッセージで再利用するため固定)
_PANEL_IMAGE_FILENAME: str = "panels.png"

# 既定モザイクラベル (mosaic 引数省略時)
_DEFAULT_MOSAIC_LABEL: str = "なし"


# ==================================================
# /start cog
# ==================================================
class StartSessionCog(commands.Cog):
    """
    `/start` スラッシュコマンドを提供する cog

    依存はコンストラクタで注入し、テスト時は mock を差し込めるようにします。
    `setup()` 関数が `Config` 経由で実装の依存を構築し、Bot に登録します。
    """

    def __init__(
        self,
        bot: commands.Bot,
        *,
        song_repository: SongRepository,
        task_generator: TaskGenerator,
        image_processor: ImageProcessor,
        session_config: SessionConfig,
        discord_config: DiscordConfig,
        session_finalizer: Optional[SessionFinalizer] = None,
        rng: Optional[random.Random] = None,
    ) -> None:
        """
        cog を初期化する

        Args:
            bot: 親 Bot インスタンス (`SDBsBot` を想定)
            song_repository: 楽曲リポジトリ (ランダム選択 / 画像パス解決に使用)
            task_generator: タスクジェネレータ (お題のランダム生成に使用)
            image_processor: 画像プロセッサ (初期画像合成 / 終了時の最終画像合成)
            session_config: セッション設定 (許容パネル数 / モザイクレベル)
            discord_config: Discord 設定 (タイマー秒数の算出に使用)
            session_finalizer: セッション終了処理 (`/end` と自動終了で共通)。
                省略時は ``image_processor`` を使った既定インスタンスを生成する。
            rng: 楽曲のランダム選択に用いる乱数生成器。テスト時に固定 seed を渡せます
        """
        super().__init__()
        self.bot: commands.Bot = bot
        self._song_repository: SongRepository = song_repository
        self._task_generator: TaskGenerator = task_generator
        self._image_processor: ImageProcessor = image_processor
        self._session_config: SessionConfig = session_config
        self._discord_config: DiscordConfig = discord_config
        self._session_finalizer: SessionFinalizer = (
            session_finalizer
            if session_finalizer is not None
            else SessionFinalizer(image_processor=image_processor)
        )
        self._rng: random.Random = rng if rng is not None else random.Random()

    # --------------------------------------------------
    # スラッシュコマンド本体
    # --------------------------------------------------
    @app_commands.command(
        name="start",
        description="新しいセッションを開始します",
    )
    @app_commands.describe(
        panels="パネル数 (4 / 9 / 16 / 25)。省略時は既定値",
        rotate="画像をランダム回転するか (90/180/270 度)",
        grayscale="画像をグレースケール化するか",
        mosaic="モザイクの強さ (なし / 弱 / 中 / 強 / 最強)",
    )
    @app_commands.choices(
        panels=_PANEL_CHOICES,
        mosaic=_MOSAIC_CHOICES,
    )
    async def start(
        self,
        interaction: discord.Interaction,
        panels: Optional[app_commands.Choice[int]] = None,
        rotate: bool = False,
        grayscale: bool = False,
        mosaic: Optional[app_commands.Choice[str]] = None,
    ) -> None:
        """
        新しいセッションを開始する

        早期失敗するパス (引数バリデーション / 既存セッション拒否) は `defer()` 前に
        ephemeral で応答し、画像合成を伴う成功パスは `defer()` で公開応答に切り替えます。
        """
        # ----- 1) 引数解決と検証 -----
        panel_count: int = (
            panels.value
            if panels is not None
            else self._session_config.default_panel_count
        )
        mosaic_label: str = (
            mosaic.value if mosaic is not None else _DEFAULT_MOSAIC_LABEL
        )

        if panel_count not in self._session_config.allowed_panel_counts:
            await interaction.response.send_message(
                f"許可されていないパネル数です: {panel_count}",
                ephemeral=True,
            )
            return
        if mosaic_label not in self._session_config.mosaic_levels:
            await interaction.response.send_message(
                f"未知のモザイクラベルです: {mosaic_label}",
                ephemeral=True,
            )
            return
        mosaic_block: int = self._session_config.mosaic_levels[mosaic_label]

        # ----- 2) 既存セッションがあれば拒否 -----
        manager: SessionManager = SessionManager.instance()
        if manager.is_active():
            await interaction.response.send_message(
                "既に進行中のセッションがあります。/end か /reset で終了してから再度開始してください。",
                ephemeral=True,
            )
            return

        # ----- 3) チャンネル検証 -----
        channel = interaction.channel
        if interaction.channel_id is None or channel is None:
            await interaction.response.send_message(
                "チャンネル外では実行できません。",
                ephemeral=True,
            )
            return

        # ----- 4) defer (画像合成中に 3 秒制限を超える可能性に備える) -----
        await interaction.response.defer()

        # ----- 5) 楽曲ランダム選択 -----
        songs = self._song_repository.all()
        if not songs:
            await interaction.followup.send(
                "楽曲データが空です。assets/data/all_songs.json を確認してください。",
                ephemeral=True,
            )
            return
        chosen = self._rng.choice(songs)

        # ----- 6) タスク生成 -----
        tasks = self._task_generator.generate(panel_count)

        # ----- 7) 初期画像合成 (全パネル未開放) -----
        image_buffer = self._image_processor.compose(
            song_name=chosen.name,
            panel_count=panel_count,
            cleared_indices=set(),
            rotate=rotate,
            grayscale=grayscale,
            mosaic_block=mosaic_block,
        )

        # ----- 8) Session 構築 -----
        session: Session = Session(
            song_name=chosen.name,
            panel_count=panel_count,
            tasks=tasks,
            channel_id=interaction.channel_id,
            owner_id=interaction.user.id,
            started_at=datetime.now(timezone.utc),
            rotate=rotate,
            grayscale=grayscale,
            mosaic_block=mosaic_block,
        )

        # ----- 9) メッセージ投稿 (タスク一覧 + パネル画像) -----
        file = discord.File(image_buffer, filename=_PANEL_IMAGE_FILENAME)
        content: str = self._build_initial_message(session, mosaic_label)
        # wait=True で送信完了 Message を取得しピン留め対象にする
        sent_message = await interaction.followup.send(
            content=content, file=file, wait=True
        )

        # ----- 10) ピン留めとメッセージ ID 保存 -----
        try:
            await sent_message.pin()
        except discord.DiscordException as e:
            # ピン留め権限が無い等のケースでも投稿自体は成功させる (要件: 握りつぶさず警告)
            logger.warning("メッセージのピン留めに失敗しました: %s", e)
        session.pinned_message_id = sent_message.id

        # ----- 11) タイマー起動 (10 分前通知 + 30 分自動終了) -----
        timeout_seconds: float = float(
            self._discord_config.session_timeout_minutes * 60
        )
        warning_seconds: float = float(
            (
                self._discord_config.session_timeout_minutes
                - self._discord_config.warning_minutes_before_end
            )
            * 60
        )

        async def on_warning() -> None:
            """`SessionManager` から呼ばれる残り時間警告コールバック"""
            await self._notify_warning(channel)

        async def on_timeout() -> None:
            """`SessionManager` から呼ばれる自動終了コールバック (`/end` 同等処理)"""
            await self._finalize_session(session, channel)

        manager.start(
            session,
            on_warning=on_warning,
            on_timeout=on_timeout,
            warning_delay_seconds=warning_seconds,
            timeout_delay_seconds=timeout_seconds,
        )

    # --------------------------------------------------
    # 内部ヘルパー
    # --------------------------------------------------
    def _build_initial_message(self, session: Session, mosaic_label: str) -> str:
        """
        セッション開始時にチャンネルへ投稿するメッセージ本文を組み立てる

        進捗表示は `/progress` で詳細化するため、ここではタスク種別と必要回数のみ並べます。
        """
        lines: list[str] = [
            "**セッション開始**",
            f"- パネル数: {session.panel_count}",
            f"- モザイク: {mosaic_label} (block={session.mosaic_block}px)",
            (
                f"- 回転: {'有効' if session.rotate else '無効'}"
                f" / グレースケール: {'有効' if session.grayscale else '無効'}"
            ),
            "",
            "**お題**",
        ]
        for index, task in enumerate(session.tasks, start=1):
            lines.append(f"{index}. {task.type} (set={task.set_value})")
        return "\n".join(lines)

    async def _notify_warning(self, channel: discord.abc.Messageable) -> None:
        """
        残り時間警告 (規定: 10 分前) をセッションチャンネルへ送信する
        """
        minutes: int = self._discord_config.warning_minutes_before_end
        try:
            await channel.send(f"⚠ セッション終了まで残り {minutes} 分です。")
        except discord.DiscordException as e:
            # チャンネル削除等で送信不能でも残り処理 (timeout 等) を妨げない
            logger.warning("残り時間警告の送信に失敗しました: %s", e)

    async def _finalize_session(
        self,
        session: Session,
        channel: discord.abc.Messageable,
    ) -> None:
        """
        セッション制限時間到達時の自動終了処理 (`/end` と同等)

        実処理は `SessionFinalizer.finalize` に委譲します (手動 /end と共通化)。
        ``summary`` には時間切れである旨を含めて区別します。
        既に手動 `/end` 等で終了済みの場合は finalizer 側で no-op となります。
        """
        notifier = getattr(self.bot, "notifier", None)
        await self._session_finalizer.finalize(
            session,
            channel,
            notifier,
            summary="セッション終了 (時間切れ)",
        )


# ==================================================
# extension エントリポイント
# ==================================================
async def setup(bot: commands.Bot) -> None:
    """
    `Bot.load_extension` から呼ばれる cog 登録関数

    実行時の依存 (リポジトリ / ジェネレータ / プロセッサ / 設定) を構築して cog に注入します。
    """
    assets = get_assets_config()
    song_repository = SongRepository(
        songs_json=assets.songs_json,
        images_dir=assets.images_dir,
    )
    task_generator = TaskGenerator(
        topics_json=assets.topics_json,
        song_repository=song_repository,
    )
    image_processor = ImageProcessor(song_repository=song_repository)

    cog = StartSessionCog(
        bot,
        song_repository=song_repository,
        task_generator=task_generator,
        image_processor=image_processor,
        session_config=get_session_config(),
        discord_config=get_discord_config(),
    )
    await bot.add_cog(cog)
