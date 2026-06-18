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
        """セッション未保持の状態で初期化する。"""
        self._session: GameSession | None = None

    @property
    def active(self) -> GameSession | None:
        """現在のアクティブセッションを返す。

        Returns:
            GameSession | None: アクティブセッション。無ければ None。
        """
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
        """新しいアクティブセッションを開始して保持する。

        Args:
            hidden_song: 出題する隠し曲(解決済み)。
            image_options: 盤面画像の加工設定(解決済み)。
            topics: 出題するお題群。
            panel_count: 盤面のパネル数。4/9/16/25 のいずれか。
            now: 開始時刻。ends_at の基準に使う。
            duration_minutes: セッションの継続時間(分)。

        Returns:
            GameSession: 生成して保持したセッション。

        Raises:
            SessionAlreadyActiveError: 既にアクティブなセッションが存在する場合。
            ValueError: panel_count が 4/9/16/25 のいずれでもない場合。
        """
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
        """プレイ申告を全お題へ照合し、新規達成パネルを開示する。

        Args:
            report: プレイ申告 1 件。

        Returns:
            list[Topic]: この申告で進捗が増えた(該当した)お題。completed が True の
                要素はこの申告で新規達成したお題を表す。

        Raises:
            NoActiveSessionError: アクティブなセッションが存在しない場合。
        """
        session = self.require_active()
        applied = match_play_report(report, session.topics)
        for topic in applied:
            if topic.completed:
                session.revealed_panels.add(topic.panel_no)
        return applied

    def record_answer(self, user_id: int, song: Song) -> bool:
        """隠し曲の当てを照合し、正解なら回答者を記録する。

        Args:
            user_id: 回答した Discord ユーザー ID。
            song: 回答として解決済みの曲。

        Returns:
            bool: 隠し曲と一致すれば True。

        Raises:
            NoActiveSessionError: アクティブなセッションが存在しない場合。
        """
        session = self.require_active()
        # 隠し曲との一致は解決済み Song の title で判定する。部分一致解決は cog の責務。
        correct = song.title == session.hidden_song.title
        # 正解順を保つため、初回正解時のみ申告順で末尾に追加する。
        if correct and user_id not in session.correct_answerers:
            session.correct_answerers.append(user_id)
        return correct

    def is_expired(self, now: datetime) -> bool:
        """セッションが有効期限を過ぎたか判定する。

        Args:
            now: 判定の基準時刻。

        Returns:
            bool: now が ends_at 以上なら True。

        Raises:
            NoActiveSessionError: アクティブなセッションが存在しない場合。
        """
        session = self.require_active()
        return now >= session.ends_at

    def remaining(self, now: datetime) -> timedelta:
        """有効期限までの残り時間を返す。

        Args:
            now: 判定の基準時刻。

        Returns:
            timedelta: ends_at - now。期限超過時は負値。

        Raises:
            NoActiveSessionError: アクティブなセッションが存在しない場合。
        """
        session = self.require_active()
        return session.ends_at - now

    def end(self) -> GameSession:
        """最終状態を返してセッションを破棄する。

        アーカイブ(画像合成・投稿)は呼び出し側が返り値を消費する。

        Returns:
            GameSession: 破棄直前の最終セッション。

        Raises:
            NoActiveSessionError: アクティブなセッションが存在しない場合。
        """
        session = self.require_active()
        self._session = None
        return session

    def clear(self) -> None:
        """アーカイブ無しでセッションを強制破棄する。

        返り値を持たないのは消費すべき最終状態が無いため。

        Raises:
            NoActiveSessionError: アクティブなセッションが存在しない場合。
        """
        self.require_active()
        self._session = None

    def require_active(self) -> GameSession:
        """アクティブセッションを返す。無ければ送出する。

        Returns:
            GameSession: 現在のアクティブセッション。

        Raises:
            NoActiveSessionError: アクティブなセッションが存在しない場合。
        """
        if self._session is None:
            raise NoActiveSessionError
        return self._session
