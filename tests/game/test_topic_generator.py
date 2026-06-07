import random

from src.game.models import (
    Chart,
    Difficulty,
    PlayCondition,
    ProgressKind,
    Song,
    TopicType,
)
from src.game.song_repository import SongRepository
from src.game.topic_catalog import CandidateSpec, RangeSpec, TopicTemplate
from src.game.topic_generator import generate_topic


def _repo() -> SongRepository:
    songs = [
        Song(
            title="Dream",
            shelf="Story",
            book="Vol.1A",
            version="1.0",
            charts={Difficulty.EASY: Chart(level=1, notes=78), Difficulty.HARD: Chart(level=8, notes=485)},
            time=133,
            composers=("Rabpit",),
            featuring=(),
            image_path=None,
        ),
        Song(
            title="Saika",
            shelf="II",
            book="Etude",
            version="2.0",
            charts={Difficulty.HARD: Chart(level=9, notes=600)},
            time=120,
            composers=("Morrigan", "Cranky"),
            featuring=(),
            image_path=None,
        ),
    ]
    return SongRepository(songs)


def test_generate_topic_is_achievable_and_formatted() -> None:
    template = TopicTemplate(
        topic_type=TopicType.LEVEL,
        description="Lv.valueの譜面を持つ楽曲をset回play",
        set_spec=(3, 5, 1),
        value_spec=RangeSpec(low=1, high=12, step=1),
    )
    rng = random.Random(0)
    topic = generate_topic(template, panel_no=4, repo=_repo(), rng=rng)

    assert topic.panel_no == 4
    assert topic.topic_type is TopicType.LEVEL
    assert 3 <= topic.required <= 5
    assert topic.progress_kind is ProgressKind.COUNT
    assert topic.progress == 0 and topic.completed is False
    # 解決値で実在曲が一致する(達成可能)。
    songs = _repo().songs
    assert any(chart.level == topic.filter_value for s in songs for chart in s.charts.values())
    # 説明に未置換トークンが残らない。
    assert "value" not in topic.description and "set" not in topic.description


def test_generate_topic_play_condition_distribution() -> None:
    template = TopicTemplate(
        topic_type=TopicType.SHELF,
        description="value棚に収録されている楽曲をset回play",
        set_spec=(3, 5, 1),
        value_spec=CandidateSpec(candidate="shelf_list", choice=1),
    )
    rng = random.Random(1)
    repo = _repo()
    conditions = [
        generate_topic(template, panel_no=1, repo=repo, rng=rng).play_condition
        for _ in range(200)
    ]
    play = conditions.count(PlayCondition.PLAY)
    # 60% 前後に寄る(おおまかな分布確認)。
    assert 100 < play < 160


def test_generate_topic_sum_type() -> None:
    template = TopicTemplate(
        topic_type=TopicType.LEVEL_TOTAL,
        description="playした譜面のレベルの合計がset",
        set_spec=(30, 50, 10),
        value_spec=None,
    )
    topic = generate_topic(template, panel_no=2, repo=_repo(), rng=random.Random(0))
    assert topic.progress_kind is ProgressKind.SUM
    assert topic.filter_value is None
    assert topic.required in (30, 40, 50)
