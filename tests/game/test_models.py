from src.game.models import (
    Chart,
    Difficulty,
    PlayCondition,
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
