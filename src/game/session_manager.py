from __future__ import annotations

from datetime import datetime, timedelta

from src.game.models import GameSession, ImageOptions, PlayReport, Song, Topic
from src.game.play_matcher import apply_report as match_play_report

_VALID_PANEL_COUNTS = frozenset({4, 9, 16, 25})


class SessionError(Exception):
    """セッション操作の基底例外。"""


class SessionAlreadyActiveError(SessionError):
    """アクティブなセッションが既に存在する。"""


class NoActiveSessionError(SessionError):
    """アクティブなセッションが存在しない。"""


class SessionManager:
    """単一プロセス内の単一アクティブセッションを管理する(再起動で揮発)。"""

    def __init__(self) -> None:
        self._session: GameSession | None = None

    @property
    def active(self) -> GameSession | None:
        return self._session

    def start(
        self,
        *,
        hidden_song: Song,
        image_options: ImageOptions,
        topics: list[Topic],
        panel_count: int,
        now: datetime,
        duration_minutes: int,
    ) -> GameSession:
        if self._session is not None:
            raise SessionAlreadyActiveError
        if panel_count not in _VALID_PANEL_COUNTS:
            raise ValueError(f"panel_count must be one of {sorted(_VALID_PANEL_COUNTS)}")
        session = GameSession(
            panel_count=panel_count,
            hidden_song=hidden_song,
            image_options=image_options,
            topics=topics,
            started_at=now,
            ends_at=now + timedelta(minutes=duration_minutes),
        )
        self._session = session
        return session

    def apply_report(self, report: PlayReport) -> list[Topic]:
        session = self._require_active()
        newly_completed = match_play_report(report, session.topics)
        for topic in newly_completed:
            session.revealed_panels.add(topic.panel_no)
        return newly_completed

    def record_answer(self, user_id: int, song: Song) -> bool:
        session = self._require_active()
        # 隠し曲との一致は解決済み Song の title で判定する。部分一致解決は cog の責務。
        correct = song.title == session.hidden_song.title
        if correct:
            session.correct_answerers.add(user_id)
        return correct

    def is_expired(self, now: datetime) -> bool:
        session = self._require_active()
        return now >= session.ends_at

    def remaining(self, now: datetime) -> timedelta:
        session = self._require_active()
        return session.ends_at - now

    def end(self) -> GameSession:
        """最終状態を返して破棄する。アーカイブ(画像合成・投稿)は呼び出し側が返り値を消費する。"""
        session = self._require_active()
        self._session = None
        return session

    def clear(self) -> None:
        """アーカイブ無しで強制破棄する。返り値を持たないのは消費すべき最終状態が無いため。"""
        self._require_active()
        self._session = None

    def _require_active(self) -> GameSession:
        if self._session is None:
            raise NoActiveSessionError
        return self._session
