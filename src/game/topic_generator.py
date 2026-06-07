from __future__ import annotations

import random

from src.game.models import FilterValue, PlayCondition, Song, Topic
from src.game.predicates import PREDICATE_BUILDERS, Predicate
from src.game.song_repository import SongRepository
from src.game.topic_catalog import RangeSpec, TopicTemplate, ValueSpec
from src.game.topic_types import TYPE_INFO, format_description

# 達成可能な value が見つからない場合の無限ループ防止。実データでは十分余裕がある。
_MAX_ATTEMPTS = 200


def _stepped_values(spec: RangeSpec) -> list[int | float]:
    count = round((spec.high - spec.low) / spec.step)
    values = [round(spec.low + i * spec.step, 6) for i in range(count + 1)]
    if all(float(v).is_integer() for v in values):
        return [int(v) for v in values]
    return values


def _candidate_pool(candidate: str | tuple[str, ...], repo: SongRepository) -> list[str]:
    if candidate == "version_list":
        return repo.versions()
    if candidate == "book_list":
        return repo.books()
    if candidate == "shelf_list":
        return repo.shelves()
    if isinstance(candidate, tuple):
        return list(candidate)
    return list(candidate)


def _resolve_value(spec: ValueSpec, repo: SongRepository, rng: random.Random) -> FilterValue:
    if spec is None:
        return None
    if isinstance(spec, RangeSpec):
        return rng.choice(_stepped_values(spec))
    pool = _candidate_pool(spec.candidate, repo)
    return tuple(sorted(rng.sample(pool, spec.choice)))


def _roll_required(set_spec: tuple[int, int, int], rng: random.Random) -> int:
    set_min, set_max, set_step = set_spec
    return rng.choice(list(range(set_min, set_max + 1, set_step)))


def _roll_play_condition(rng: random.Random) -> PlayCondition:
    roll = rng.random()
    if roll < 0.6:
        return PlayCondition.PLAY
    if roll < 0.9:
        return PlayCondition.FULL_COMBO
    return PlayCondition.ALL_CHARMING


def _is_achievable(predicate: Predicate, songs: list[Song]) -> bool:
    return any(predicate(song, difficulty) for song in songs for difficulty in song.charts)


def generate_topic(
    template: TopicTemplate,
    panel_no: int,
    repo: SongRepository,
    rng: random.Random,
) -> Topic:
    info = TYPE_INFO[template.topic_type]
    builder = PREDICATE_BUILDERS[template.topic_type]
    songs = repo.songs
    for _ in range(_MAX_ATTEMPTS):
        required = _roll_required(template.set_spec, rng)
        value = _resolve_value(template.value_spec, repo, rng)
        play_condition = _roll_play_condition(rng)
        if not _is_achievable(builder(value), songs):
            continue
        description = format_description(
            topic_type=template.topic_type,
            description=template.description,
            value=value,
            required=required,
            play_condition=play_condition,
        )
        return Topic(
            panel_no=panel_no,
            topic_type=template.topic_type,
            play_condition=play_condition,
            filter_value=value,
            required=required,
            progress_kind=info.progress_kind,
            description=description,
        )
    raise RuntimeError(f"達成可能なお題を生成できません: {template.topic_type.value}")


def _choose_templates(
    templates: list[TopicTemplate],
    count: int,
    rng: random.Random,
) -> list[TopicTemplate]:
    if count <= len(templates):
        return rng.sample(templates, count)
    # 型数を超える分は重複を許して補い、並びを混ぜる。
    chosen = list(templates)
    chosen += [rng.choice(templates) for _ in range(count - len(templates))]
    rng.shuffle(chosen)
    return chosen


def generate_topics(
    templates: list[TopicTemplate],
    count: int,
    repo: SongRepository,
    rng: random.Random,
) -> list[Topic]:
    chosen = _choose_templates(templates, count, rng)
    return [
        generate_topic(template, panel_no=index + 1, repo=repo, rng=rng)
        for index, template in enumerate(chosen)
    ]
