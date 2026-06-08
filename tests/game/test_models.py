from datetime import datetime

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


def test_song_construction() -> None:
    song = Song(
        title="Dream",
        shelf="Story",
        book="Deemo's collection Vol.1A",
        version="1.0",
        charts={Difficulty.HARD: Chart(level=8, notes=485)},
        time=133,
        composers=("Rabpit",),
        featuring=(),
        image_path=None,
    )
    assert song.charts[Difficulty.HARD].notes == 485
    assert song.featuring == ()
    assert Difficulty.EASY.value == "Easy"


def test_topic_construction_defaults() -> None:
    topic = Topic(
        panel_no=1,
        topic_type=TopicType.TITLE_INCLUDE,
        play_condition=PlayCondition.PLAY,
        filter_value=("a", "c"),
        required=3,
        progress_kind=ProgressKind.COUNT,
        description="楽曲名に(a, c)のすべてが含まれる楽曲を3回play",
    )
    assert topic.progress == 0
    assert topic.completed is False
    assert TopicType("title_include") is TopicType.TITLE_INCLUDE
    assert PlayCondition.FULL_COMBO.value == "FC"
    assert ProgressKind.SUM.value == "SUM"


def test_topic_progress_is_mutable() -> None:
    topic = Topic(
        panel_no=2,
        topic_type=TopicType.LEVEL_TOTAL,
        play_condition=PlayCondition.ALL_CHARMING,
        filter_value=None,
        required=40,
        progress_kind=ProgressKind.SUM,
        description="ACした譜面のレベルの合計が40",
    )
    topic.progress += 8
    topic.completed = True
    assert topic.progress == 8
    assert topic.completed is True


def test_image_options_construction() -> None:
    opts = ImageOptions(rotate=90, grayscale=True, mosaic_px=150)
    assert opts.rotate == 90
    assert opts.grayscale is True
    assert opts.mosaic_px == 150


def test_game_session_defaults_and_grid_size() -> None:
    song = Song(
        title="Dream",
        shelf="Story",
        book="Vol.1A",
        version="1.0",
        charts={Difficulty.HARD: Chart(level=8, notes=485)},
        time=133,
        composers=("Rabpit",),
        featuring=(),
        image_path=None,
    )
    session = GameSession(
        panel_count=9,
        hidden_song=song,
        image_options=ImageOptions(rotate=None, grayscale=False, mosaic_px=None),
        topics=[],
        started_at=datetime(2026, 6, 8, 12, 0, 0),
        ends_at=datetime(2026, 6, 8, 12, 30, 0),
    )
    assert session.grid_size == 3
    assert session.revealed_panels == set()
    assert session.correct_answerers == set()


def test_game_session_grid_size_for_each_panel_count() -> None:
    song = Song(
        title="Dream",
        shelf="Story",
        book="Vol.1A",
        version="1.0",
        charts={Difficulty.HARD: Chart(level=8, notes=485)},
        time=133,
        composers=("Rabpit",),
        featuring=(),
        image_path=None,
    )
    options = ImageOptions(rotate=None, grayscale=False, mosaic_px=None)
    start = datetime(2026, 6, 8, 12, 0, 0)
    end = datetime(2026, 6, 8, 12, 30, 0)
    expected = {4: 2, 9: 3, 16: 4, 25: 5}
    for panel_count, grid in expected.items():
        session = GameSession(
            panel_count=panel_count,
            hidden_song=song,
            image_options=options,
            topics=[],
            started_at=start,
            ends_at=end,
        )
        assert session.grid_size == grid


def test_play_report_construction() -> None:
    song = Song(
        title="Dream",
        shelf="Story",
        book="Vol.1A",
        version="1.0",
        charts={Difficulty.HARD: Chart(level=8, notes=485)},
        time=133,
        composers=("Rabpit",),
        featuring=(),
        image_path=None,
    )
    report = PlayReport(
        song=song,
        difficulty=Difficulty.HARD,
        combo=485,
        charming=400,
    )
    assert report.song.title == "Dream"
    assert report.difficulty is Difficulty.HARD
    assert report.combo == 485
    assert report.charming == 400
