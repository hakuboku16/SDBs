import json
from pathlib import Path

from src.game.models import TopicType
from src.game.topic_catalog import (
    CandidateSpec,
    RangeSpec,
    TopicTemplate,
    load_topics,
)


def _write(tmp_path: Path) -> Path:
    data = [
        {
            "type": "title_include",
            "description": "楽曲名にvalueのすべてが含まれる楽曲をset回play",
            "set": [2, 4, 1],
            "value": {"candidate": "abcdefghijklmnopqrstuvwxyz", "choice": 2},
        },
        {
            "type": "difficult",
            "description": "難易度valueでset回play",
            "set": [3, 5, 1],
            "value": {"candidate": ["Easy", "Normal", "Hard"], "choice": 1},
        },
        {
            "type": "level",
            "description": "Lv.valueの譜面を持つ楽曲をset回play",
            "set": [3, 5, 1],
            "value": {"range": [1, 12, 1]},
        },
        {
            "type": "level_total",
            "description": "playした譜面のレベルの合計がset",
            "set": [30, 50, 10],
            "value": None,
        },
        {
            "type": "version",
            "description": "ver.valueに実装された楽曲をset回play",
            "set": [1, 3, 1],
            "value": {"candidate": "version_list", "choice": 3},
        },
    ]
    path = tmp_path / "all_topics.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_load_parses_all_value_shapes(tmp_path: Path) -> None:
    templates = load_topics(_write(tmp_path))
    by_type = {t.topic_type: t for t in templates}

    char_pool = by_type[TopicType.TITLE_INCLUDE]
    assert char_pool.set_spec == (2, 4, 1)
    assert isinstance(char_pool.value_spec, CandidateSpec)
    assert char_pool.value_spec.candidate == "abcdefghijklmnopqrstuvwxyz"
    assert char_pool.value_spec.choice == 2

    difficult = by_type[TopicType.DIFFICULT]
    assert isinstance(difficult.value_spec, CandidateSpec)
    assert difficult.value_spec.candidate == ("Easy", "Normal", "Hard")

    level = by_type[TopicType.LEVEL]
    assert isinstance(level.value_spec, RangeSpec)
    assert (level.value_spec.low, level.value_spec.high, level.value_spec.step) == (1, 12, 1)

    assert by_type[TopicType.LEVEL_TOTAL].value_spec is None

    version = by_type[TopicType.VERSION]
    assert isinstance(version.value_spec, CandidateSpec)
    assert version.value_spec.candidate == "version_list"


def test_returns_topic_template_instances(tmp_path: Path) -> None:
    templates = load_topics(_write(tmp_path))
    assert all(isinstance(t, TopicTemplate) for t in templates)
    assert len(templates) == 5
