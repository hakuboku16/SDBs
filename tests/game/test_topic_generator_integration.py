import random
from pathlib import Path

from src.game.predicates import PREDICATE_BUILDERS
from src.game.song_repository import SongRepository
from src.game.topic_catalog import load_topics
from src.game.topic_generator import generate_topics

ASSETS = Path(__file__).resolve().parents[2] / "assets"


def test_real_data_generates_achievable_topics() -> None:
    repo = SongRepository.from_files(
        ASSETS / "data" / "all_songs.json",
        ASSETS / "images",
    )
    templates = load_topics(ASSETS / "data" / "all_topics.json")
    songs = repo.songs

    topics = generate_topics(templates, count=9, repo=repo, rng=random.Random(42))

    assert [t.panel_no for t in topics] == list(range(1, 10))
    for topic in topics:
        assert topic.description
        assert "value" not in topic.description
        predicate = PREDICATE_BUILDERS[topic.topic_type](topic.filter_value)
        assert any(
            predicate(song, difficulty) for song in songs for difficulty in song.charts
        ), f"達成不能なお題が生成された: {topic.topic_type.value}"
