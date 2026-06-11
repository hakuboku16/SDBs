from __future__ import annotations

import random
from datetime import datetime
from pathlib import Path

from src.core.config import BaseAppSettings
from src.game.board import render_board
from src.game.image_options import resolve_image_options
from src.game.models import GameSession, Song, Topic
from src.game.session_manager import NoActiveSessionError, SessionManager
from src.game.song_repository import SongRepository
from src.game.topic_catalog import TopicTemplate, load_topics
from src.game.topic_generator import generate_topics

GENERIC_ERROR_MESSAGE = "コマンドの実行中にエラーが発生しました。しばらくして再度お試しください。"


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
        # Discord 側状態。実体は後続タスクで discord.Message / asyncio.Task を入れる。
        self.board_message: object | None = None
        self.topic_message: object | None = None
        self.timer_task: object | None = None

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
        """部分一致で曲を 1 件に解決する。

        Args:
            query: 検索語。

        Returns:
            Song: 一意に解決した曲。

        Raises:
            SongNotFound: 部分一致が 0 件の場合。
            AmbiguousSong: 部分一致が複数件の場合。
        """
        matches = self._repo.search(query)
        if not matches:
            raise SongNotFound(query)
        if len(matches) > 1:
            raise AmbiguousSong(matches)
        return matches[0]

    @property
    def session(self) -> GameSession | None:
        """現在のアクティブセッションを返す。

        Returns:
            GameSession | None: アクティブセッション。無ければ None。
        """
        return self.session_manager.active

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
        session = self.session_manager._require_active()
        assert session.hidden_song.image_path is not None  # 隠し曲は画像保有曲から抽選済み
        return render_board(
            session.hidden_song.image_path,
            grid_size=session.grid_size,
            revealed_panels=session.revealed_panels,
            options=session.image_options,
        )

    def cancel_timer(self) -> None:
        """進行中のタイマータスクがあれば取り消す。"""
        # 手動終了/強制クリア時に自動終了タイマーが二重発火しないよう取り消す。
        if self.timer_task is not None:
            self.timer_task.cancel()
            self.timer_task = None
