from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path

import discord

from src.bot import embeds
from src.core.config import BaseAppSettings
from src.game.board import CANVAS_SIZE, render_board
from src.game.image_options import resolve_image_options
from src.game.models import GameSession, Song, Topic
from src.game.session_manager import SessionManager
from src.game.song_repository import SongRepository
from src.game.topic_catalog import TopicTemplate, load_topics
from src.game.topic_generator import generate_topics

GENERIC_ERROR_MESSAGE = (
    "コマンドの実行中にエラーが発生しました。しばらくして再度お試しください。"
)
BOARD_FILENAME = "board.png"
SESSION_EMBED_TITLE = "🎯 セッション開始"
ARCHIVE_EMBED_TITLE = "🎵 セッション結果"
SESSION_END_TITLE = "⏱️ 制限時間終了"
SESSION_END_MESSAGE = (
    "セッションの制限時間が終了しました。\n結果は別チャンネルに送信されます。"
)

# モザイク強度の選択肢。value は縮小先 px(0=なし)。表示は実効解像度 px を併記する。
MOSAIC_OPTIONS: list[tuple[str, int]] = [
    ("なし", 0),
    ("弱", 150),
    ("中", 90),
    ("強", 45),
    ("最強", 27),
]
_MOSAIC_NAME_BY_PX = {px: name for name, px in MOSAIC_OPTIONS}


def mosaic_choice_label(name: str, px: int) -> str:
    """モザイク選択肢の表示ラベルを「名前 (実効解像度px)」で組み立てる。

    Args:
        name: 強度の表示名(なし/弱/中/強/最強)。
        px: 縮小先 px。0 は縮小なし(なし)を表す。

    Returns:
        str: 「なし (300px)」のように実効解像度を併記したラベル。
    """
    # px=0(なし)は縮小しないため、実効解像度は盤面キャンバスの一辺になる。
    effective = px if px else CANVAS_SIZE
    return f"{name} ({effective}px)"


class SongResolutionError(Exception):
    """曲名解決に関する基底例外。"""


class SongNotFound(SongResolutionError):
    """部分一致する曲が 1 件も無い。"""

    def __init__(self, query: str) -> None:
        """解決に失敗した検索語を保持する。

        Args:
            query: 解決に失敗した検索語。
        """
        super().__init__(query)
        self.query = query


class AmbiguousSong(SongResolutionError):
    """部分一致する曲が複数あり 1 件に絞れない。"""

    def __init__(self, matches: list[Song]) -> None:
        """候補となった曲群を保持する。

        Args:
            matches: 部分一致した複数の曲。
        """
        super().__init__(f"{len(matches)} matches")
        self.matches = matches


def format_topic_list(topics: list[Topic]) -> str:
    """ピン留め用のお題リスト文字列を生成する。

    Args:
        topics: 表示するお題群。

    Returns:
        str: パネル番号昇順に「パネルN: 説明 [progress/required]」を改行連結した文字列。
            達成済みの行には末尾に「 達成」を付ける。
    """
    lines: list[str] = []
    for topic in sorted(topics, key=lambda t: t.panel_no):
        line = f"パネル{topic.panel_no}: {topic.description} [{topic.progress}/{topic.required}]"
        if topic.completed:
            line += " 達成"
        lines.append(line)
    return "\n".join(lines)


def format_session_options(session: GameSession) -> str:
    """お題生成オプションを盤面 Embed 用に整形する。

    Args:
        session: 表示対象のセッション。

    Returns:
        str: パネル数・回転・グレースケール・モザイクを箇条書きにした文字列。
    """
    options = session.image_options
    rotate = "有効" if options.rotate is not None else "無効"
    grayscale = "有効" if options.grayscale else "無効"
    px = options.mosaic_px or 0
    mosaic = mosaic_choice_label(_MOSAIC_NAME_BY_PX[px], px)
    return "\n".join(
        [
            f"・パネル数:{session.panel_count}",
            f"・回転:{rotate}",
            f"・グレースケール:{grayscale}",
            f"・モザイク:{mosaic}",
        ]
    )


def format_panel_list(topics: list[Topic]) -> str:
    """お題をパネル番号順に達成マーク付きで整形する。

    Args:
        topics: 表示するお題群。

    Returns:
        str: パネル番号昇順に「{✅/⬜} パネル N (progress/required)」と説明を
            改行で並べた文字列。達成済みは ✅、未達成は ⬜ を付ける。
    """
    lines: list[str] = []
    for topic in sorted(topics, key=lambda t: t.panel_no):
        mark = "✅" if topic.completed else "⬜"
        lines.append(
            f"{mark} **パネル {topic.panel_no} ({topic.progress}/{topic.required})**"
        )
        lines.append(topic.description)
    return "\n".join(lines)


def format_archive_caption(session: GameSession) -> str:
    """セッション結果アーカイブ用の文言を生成する。

    Args:
        session: 終了するセッション。

    Returns:
        str: 楽曲名+パック名(book)をネタバレ記法で隠し、正解者を正解順で
            列挙した文言。正解者がいなければ「正解者なし」を表示する。
    """
    song = session.hidden_song
    if session.correct_answerers:
        answerers = "\n".join(f"<@{uid}>" for uid in session.correct_answerers)
    else:
        answerers = "正解者なし"
    return f"楽曲名: ||{song.title} ({song.book})||\n正解者:\n{answerers}"


def format_progress_text(session: GameSession, remaining: timedelta) -> str:
    """進捗表示(残り時間 + お題リスト)を整形する。

    Args:
        session: 表示対象のセッション。
        remaining: 終了までの残り時間。負値は 0 分として扱う。

    Returns:
        str: 残り時間とお題リストを併記した文字列。
    """
    minutes = max(int(remaining.total_seconds() // 60), 0)
    return f"残り時間: 約{minutes}分\n\n{format_topic_list(session.topics)}"


def timer_delays(
    session: GameSession, *, now: datetime, warning_minutes: int
) -> tuple[float, float]:
    """セッションの予告までと終了までの待機秒数を計算する。

    Args:
        session: 対象セッション。ends_at を基準にする。
        now: 現在時刻。
        warning_minutes: 終了の何分前に予告するか。

    Returns:
        tuple[float, float]: (予告までの秒数, 終了までの秒数)。
    """
    end_seconds = (session.ends_at - now).total_seconds()
    warning_seconds = end_seconds - warning_minutes * 60
    return warning_seconds, end_seconds


class GameService:
    """ゲーム層と Discord 側セッション文脈を集約する bot 層ファサード。

    cog はこのサービスへ委譲するだけの薄いアダプタに留める。game/ の純粋性を保つため、
    Discord 由来の状態(メッセージ参照・タイマータスク)はここに保持する。
    """

    def __init__(
        self,
        *,
        repo: SongRepository,
        templates: list[TopicTemplate],
        settings: BaseAppSettings,
        rng: random.Random | None = None,
    ) -> None:
        """依存と Discord 側状態スロットを初期化する。

        Args:
            repo: 楽曲リポジトリ。
            templates: お題テンプレート群。
            settings: アプリ設定(セッション時間・チャンネル ID 等)。
            rng: 抽選に使う乱数源。None なら既定の乱数源を使う。
        """
        self._repo = repo
        self._templates = templates
        self._settings = settings
        self._rng = rng or random.Random()
        self.session_manager = SessionManager()
        # Discord 側状態。投稿・タイマー開始時に実体を入れる。
        # 盤面画像とお題リストを1つの Embed メッセージにまとめて保持する。
        self.session_message: discord.Message | None = None
        self.timer_task: asyncio.Task[None] | None = None

    @classmethod
    def from_settings(
        cls,
        settings: BaseAppSettings,
        *,
        rng: random.Random | None = None,
    ) -> GameService:
        """設定のパスから楽曲・お題を読み込んで生成する。

        Args:
            settings: アプリ設定。データパスを参照する。
            rng: 抽選に使う乱数源。None なら既定の乱数源を使う。

        Returns:
            GameService: 構築したサービス。
        """
        repo = SongRepository.from_files(
            Path(settings.songs_data_path), Path(settings.images_dir)
        )
        templates = load_topics(Path(settings.topics_data_path))
        return cls(repo=repo, templates=templates, settings=settings, rng=rng)

    def resolve_song(self, query: str) -> Song:
        """部分一致で曲を 1 件に解決する。完全一致する曲名があれば優先する。

        Args:
            query: 検索語。

        Returns:
            Song: 一意に解決した曲。

        Raises:
            SongNotFound: 部分一致が 0 件の場合。
            AmbiguousSong: 完全一致が無く部分一致が複数件の場合。
        """
        matches = self._repo.search(query)
        if not matches:
            raise SongNotFound(query)
        # オートコンプリートで選んだ曲名が別曲名の部分文字列でも確実に解決できるよう、
        # 完全一致する曲があればそれを優先する。
        exact = self._repo.find_exact(query)
        if exact is not None:
            return exact
        if len(matches) > 1:
            raise AmbiguousSong(matches)
        return matches[0]

    def suggest_song_titles(self, query: str, *, limit: int = 25) -> list[str]:
        """オートコンプリート用に曲名候補を返す。

        Args:
            query: 入力中の検索語。空なら全曲が対象。
            limit: 返す最大件数。Discord の候補上限に合わせ既定 25。

        Returns:
            list[str]: 曲名昇順で先頭 limit 件の曲名。
        """
        songs = self._repo.songs if not query.strip() else self._repo.search(query)
        titles = sorted(song.title for song in songs)
        return titles[:limit]

    @property
    def session(self) -> GameSession | None:
        """現在のアクティブセッションを返す。

        Returns:
            GameSession | None: アクティブセッション。無ければ None。
        """
        return self.session_manager.active

    @property
    def settings(self) -> BaseAppSettings:
        """保持するアプリ設定を返す。

        Returns:
            BaseAppSettings: チャンネル ID・セッション時間等の設定。
        """
        return self._settings

    def start_session(
        self,
        *,
        panel_count: int,
        rotate: bool,
        grayscale: bool,
        mosaic_px: int | None,
        now: datetime,
    ) -> GameSession:
        """隠し曲抽選・画像設定確定・お題生成を束ねてセッションを開始する。

        Args:
            panel_count: 盤面パネル数。4/9/16/25 のいずれか。
            rotate: 回転を行うか。
            grayscale: グレースケール化するか。
            mosaic_px: モザイクの縮小先 px。None ならモザイクなし。
            now: 開始時刻。ends_at の基準に使う。

        Returns:
            GameSession: 開始して保持したセッション。

        Raises:
            SessionAlreadyActiveError: 既にアクティブなセッションがある場合。
            ValueError: panel_count が 4/9/16/25 のいずれでもない場合。
        """
        hidden_song = self._rng.choice(self._repo.songs_with_image())
        image_options = resolve_image_options(
            rotate=rotate, grayscale=grayscale, mosaic_px=mosaic_px, rng=self._rng
        )
        topics = generate_topics(self._templates, panel_count, self._repo, self._rng)
        return self.session_manager.start(
            hidden_song=hidden_song,
            image_options=image_options,
            topics=topics,
            panel_count=panel_count,
            now=now,
            duration_minutes=self._settings.session_duration_minutes,
        )

    def render_current_board(self) -> bytes:
        """アクティブセッションの現在の盤面 PNG を生成する。

        Returns:
            bytes: PNG エンコードした盤面画像。

        Raises:
            NoActiveSessionError: アクティブなセッションが無い場合。
        """
        session = self.session_manager.require_active()
        assert (
            session.hidden_song.image_path is not None
        )  # 隠し曲は画像保有曲から抽選済み
        return render_board(
            session.hidden_song.image_path,
            grid_size=session.grid_size,
            revealed_panels=session.revealed_panels,
            options=session.image_options,
        )

    def _build_session_embed(self) -> discord.Embed:
        """盤面画像・生成オプション・お題一覧を1つにまとめた Embed を組み立てる。

        Returns:
            discord.Embed: オプションとお題一覧を本文に持ち、盤面画像を添付参照する青色 Embed。

        Raises:
            NoActiveSessionError: アクティブなセッションが無い場合。
        """
        session = self.session_manager.require_active()
        body = (
            f"{format_session_options(session)}\n\n{format_panel_list(session.topics)}"
        )
        embed = embeds.info(body, title=SESSION_EMBED_TITLE)
        embed.set_image(url=f"attachment://{BOARD_FILENAME}")
        return embed

    def cancel_timer(self) -> None:
        """進行中のタイマータスクがあれば取り消す。"""
        # 手動終了/強制クリア時に自動終了タイマーが二重発火しないよう取り消す。
        if self.timer_task is not None:
            self.timer_task.cancel()
            self.timer_task = None

    async def post_session_messages(self, channel: discord.abc.Messageable) -> None:
        """盤面とお題リストを1つの Embed として投稿しピン留めし、参照を保持する。

        Args:
            channel: 投稿先チャンネル。
        """
        png = self.render_current_board()
        message = await channel.send(
            embed=self._build_session_embed(),
            file=discord.File(BytesIO(png), filename=BOARD_FILENAME),
        )
        await message.pin()
        self.session_message = message

    async def refresh_board(self) -> None:
        """盤面画像とお題リストの Embed メッセージを現在の状態へ更新する。"""
        if self.session_message is None:
            return
        png = self.render_current_board()
        await self.session_message.edit(
            embed=self._build_session_embed(),
            attachments=[discord.File(BytesIO(png), filename=BOARD_FILENAME)],
        )

    async def end_session(
        self, archive_channel: discord.abc.Messageable
    ) -> GameSession:
        """現時点の盤面をアーカイブし、ピンを解除してセッションを終了する。

        Args:
            archive_channel: アーカイブ投稿先チャンネル。

        Returns:
            GameSession: 終了直前の最終セッション。

        Raises:
            NoActiveSessionError: アクティブなセッションが無い場合。
        """
        session = self.session_manager.require_active()
        png = self.render_current_board()
        archive_embed = embeds.neutral(
            format_archive_caption(session), title=ARCHIVE_EMBED_TITLE
        )
        archive_embed.set_image(url=f"attachment://{BOARD_FILENAME}")
        await archive_channel.send(
            embed=archive_embed,
            file=discord.File(BytesIO(png), filename=BOARD_FILENAME),
        )
        await self._unpin_messages()
        # 自動終了経由ではタイマー自身がこの後終了するため、ここでは取り消さず参照だけ落とす。
        self.timer_task = None
        return self.session_manager.end()

    async def clear_session(self) -> None:
        """アーカイブせずにセッションを強制破棄する。

        Raises:
            NoActiveSessionError: アクティブなセッションが無い場合。
        """
        self.cancel_timer()
        await self._unpin_messages()
        self.session_manager.clear()

    async def _unpin_messages(self) -> None:
        """盤面+お題メッセージのピンを解除し、参照を落とす。"""
        if self.session_message is not None:
            await self.session_message.unpin()
        self.session_message = None

    async def run_timer(
        self, archive_channel: discord.abc.Messageable, *, now: datetime
    ) -> None:
        """予告と自動終了を行うタイマーを実走する。

        Args:
            archive_channel: 自動終了時のアーカイブ投稿先。
            now: 開始時刻。残り時間計算の基準。
        """
        session = self.session_manager.require_active()
        warning_minutes = self._settings.session_warning_minutes
        warning_seconds, end_seconds = timer_delays(
            session, now=now, warning_minutes=warning_minutes
        )
        if warning_seconds > 0:
            await asyncio.sleep(warning_seconds)
        if self.session_message is not None:
            await self.session_message.channel.send(
                embed=embeds.warning(
                    f"セッションの制限時間まで残り{warning_minutes}分です。\n"
                    "まだ回答していない方はお早めに。",
                    title=f"⏰ 残り時間: {warning_minutes}分",
                )
            )
        await asyncio.sleep(max(end_seconds - max(warning_seconds, 0.0), 0.0))
        # 制限時間終了時も手動 /session_end と同じ終了告知を盤面チャンネルへ送る。
        if self.session_message is not None:
            await self.session_message.channel.send(
                embed=embeds.neutral(SESSION_END_MESSAGE, title=SESSION_END_TITLE)
            )
        await self.end_session(archive_channel)
