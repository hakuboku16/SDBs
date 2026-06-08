from datetime import datetime, timedelta

import pytest

from src.game.models import (
    Chart,
    Difficulty,
    GameSession,
    ImageOptions,
    PlayCondition,
    PlayReport,
    ProgressKind,
    Song,
    Topic,
    TopicType,
)
from src.game.session_manager import (
    NoActiveSessionError,
    SessionAlreadyActiveError,
    SessionManager,
)

_NOW = datetime(2026, 6, 8, 12, 0, 0)


def _song(title: str = "Dream") -> Song:
    return Song(
        title=title,
        shelf="Story",
        book="Vol.1A",
        version="1.0",
        charts={Difficulty.HARD: Chart(level=8, notes=485)},
        time=133,
        composers=("Rabpit",),
        featuring=(),
        image_path=None,
    )


def _options() -> ImageOptions:
    return ImageOptions(rotate=None, grayscale=False, mosaic_px=None)


def _topic(
    *,
    topic_type: TopicType = TopicType.TITLE_INCLUDE,
    filter_value: object = ("d",),
    required: int = 1,
    panel_no: int = 1,
) -> Topic:
    return Topic(
        panel_no=panel_no,
        topic_type=topic_type,
        play_condition=PlayCondition.PLAY,
        filter_value=filter_value,
        required=required,
        progress_kind=ProgressKind.COUNT,
        description="dummy",
    )


def _report(song: Song | None = None) -> PlayReport:
    return PlayReport(
        song=song if song is not None else _song(),
        difficulty=Difficulty.HARD,
        combo=485,
        charming=485,
    )


def _started(
    manager: SessionManager,
    *,
    topics: list[Topic] | None = None,
    song: Song | None = None,
) -> GameSession:
    return manager.start(
        hidden_song=song if song is not None else _song(),
        image_options=_options(),
        topics=topics if topics is not None else [_topic()],
        panel_count=9,
        now=_NOW,
        duration_minutes=30,
    )


def _active(manager: SessionManager) -> GameSession:
    # active は None を返しうるため、None でないことを表明してから参照する。
    session = manager.active
    assert session is not None
    return session


def test_start_creates_active_session() -> None:
    manager = SessionManager()
    session = _started(manager)
    assert manager.active is session
    assert session.grid_size == 3
    assert session.ends_at == _NOW + timedelta(minutes=30)


def test_start_rejects_when_already_active() -> None:
    manager = SessionManager()
    _started(manager)
    with pytest.raises(SessionAlreadyActiveError):
        _started(manager)


def test_start_rejects_invalid_panel_count() -> None:
    manager = SessionManager()
    with pytest.raises(ValueError):
        manager.start(
            hidden_song=_song(),
            image_options=_options(),
            topics=[_topic()],
            panel_count=10,
            now=_NOW,
            duration_minutes=30,
        )


def test_apply_report_progresses_and_reveals_panel() -> None:
    manager = SessionManager()
    topic = _topic(required=1, panel_no=5)
    _started(manager, topics=[topic])
    newly = manager.apply_report(_report())
    assert newly == [topic]
    assert _active(manager).revealed_panels == {5}


def test_apply_report_without_session_raises() -> None:
    manager = SessionManager()
    with pytest.raises(NoActiveSessionError):
        manager.apply_report(_report())


def test_record_answer_correct_records_user() -> None:
    manager = SessionManager()
    _started(manager, song=_song("Dream"))
    assert manager.record_answer(42, _song("Dream")) is True
    assert _active(manager).correct_answerers == {42}


def test_record_answer_wrong_does_not_record() -> None:
    manager = SessionManager()
    _started(manager, song=_song("Dream"))
    assert manager.record_answer(42, _song("Nine")) is False
    assert _active(manager).correct_answerers == set()


def test_is_expired_and_remaining() -> None:
    manager = SessionManager()
    _started(manager)
    assert manager.is_expired(_NOW + timedelta(minutes=29)) is False
    assert manager.is_expired(_NOW + timedelta(minutes=30)) is True
    assert manager.remaining(_NOW + timedelta(minutes=10)) == timedelta(minutes=20)


def test_end_returns_session_and_allows_restart() -> None:
    manager = SessionManager()
    started = _started(manager)
    ended = manager.end()
    assert ended is started
    assert manager.active is None
    _started(manager)  # 終了後は再開できる
    assert manager.active is not None


def test_clear_discards_and_allows_restart() -> None:
    manager = SessionManager()
    _started(manager)
    manager.clear()
    assert manager.active is None
    _started(manager)
    assert manager.active is not None


def test_end_without_session_raises() -> None:
    manager = SessionManager()
    with pytest.raises(NoActiveSessionError):
        manager.end()


def test_clear_without_session_raises() -> None:
    manager = SessionManager()
    with pytest.raises(NoActiveSessionError):
        manager.clear()
