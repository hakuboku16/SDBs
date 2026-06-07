from __future__ import annotations

from collections.abc import Callable
from typing import cast

from src.game.models import Difficulty, FilterValue, Song, TopicType

Predicate = Callable[[Song, Difficulty], bool]
PredicateBuilder = Callable[[FilterValue], Predicate]

PREDICATE_BUILDERS: dict[TopicType, PredicateBuilder] = {}


def _register(topic_type: TopicType) -> Callable[[PredicateBuilder], PredicateBuilder]:
    # 中央の辞書リテラルを編集せず型ごとに自己登録させ、型の追加を局所化する。
    def deco(builder: PredicateBuilder) -> PredicateBuilder:
        PREDICATE_BUILDERS[topic_type] = builder
        return builder

    return deco


def _chars(value: FilterValue) -> tuple[str, ...]:
    return cast(tuple[str, ...], value)


@_register(TopicType.TITLE_INCLUDE)
def _title_include(value: FilterValue) -> Predicate:
    chars = _chars(value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        title = song.title.casefold()
        return all(ch in title for ch in chars)

    return pred


@_register(TopicType.TITLE_STARTSWITH)
def _title_startswith(value: FilterValue) -> Predicate:
    chars = _chars(value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        return song.title.casefold().startswith(chars)

    return pred


@_register(TopicType.TITLE_ENDSWITH)
def _title_endswith(value: FilterValue) -> Predicate:
    chars = _chars(value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        return song.title.casefold().endswith(chars)

    return pred


@_register(TopicType.TITLE_LEN_BELOW)
def _title_len_below(value: FilterValue) -> Predicate:
    threshold = cast(int, value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        return len(song.title) <= threshold

    return pred


@_register(TopicType.TITLE_LEN_ABOVE)
def _title_len_above(value: FilterValue) -> Predicate:
    threshold = cast(int, value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        return len(song.title) >= threshold

    return pred


@_register(TopicType.TITLE_BLANK)
def _title_blank(value: FilterValue) -> Predicate:
    count = cast(int, value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        return song.title.count(" ") == count

    return pred


@_register(TopicType.DIFFICULT)
def _difficult(value: FilterValue) -> Predicate:
    allowed = _chars(value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        return difficulty.value in allowed

    return pred


@_register(TopicType.LEVEL)
def _level(value: FilterValue) -> Predicate:
    level = cast(int, value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        return any(chart.level == level for chart in song.charts.values())

    return pred


def _always_true(value: FilterValue) -> Predicate:
    # SUM 型はフィルタを持たず全プレイを累積対象にする。
    def pred(song: Song, difficulty: Difficulty) -> bool:
        return True

    return pred


PREDICATE_BUILDERS[TopicType.LEVEL_TOTAL] = _always_true
PREDICATE_BUILDERS[TopicType.RESULT_COMBO_TOTAL] = _always_true
PREDICATE_BUILDERS[TopicType.RESULT_CHARMING_TOTAL] = _always_true


@_register(TopicType.NOTES_BELOW)
def _notes_below(value: FilterValue) -> Predicate:
    threshold = cast(int, value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        return any(chart.notes <= threshold for chart in song.charts.values())

    return pred


@_register(TopicType.NOTES_ABOVE)
def _notes_above(value: FilterValue) -> Predicate:
    threshold = cast(int, value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        return any(chart.notes >= threshold for chart in song.charts.values())

    return pred


@_register(TopicType.NOTES_DENSITY_BELOW)
def _notes_density_below(value: FilterValue) -> Predicate:
    threshold = cast(float, value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        return any(chart.notes / song.time <= threshold for chart in song.charts.values())

    return pred


@_register(TopicType.NOTES_DENSITY_ABOVE)
def _notes_density_above(value: FilterValue) -> Predicate:
    threshold = cast(float, value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        return any(chart.notes / song.time >= threshold for chart in song.charts.values())

    return pred


@_register(TopicType.NOTES_ENDSWITH)
def _notes_endswith(value: FilterValue) -> Predicate:
    digits = _chars(value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        return any(str(chart.notes).endswith(digits) for chart in song.charts.values())

    return pred


@_register(TopicType.COMPOSER_NAME_STARTSWITH)
def _composer_name_startswith(value: FilterValue) -> Predicate:
    chars = _chars(value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        return any(name.casefold().startswith(chars) for name in song.composers)

    return pred


@_register(TopicType.COMPOSER_NAME_ENDSWITH)
def _composer_name_endswith(value: FilterValue) -> Predicate:
    chars = _chars(value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        return any(name.casefold().endswith(chars) for name in song.composers)

    return pred


@_register(TopicType.COMPOSER_MEMBERS)
def _composer_members(value: FilterValue) -> Predicate:
    def pred(song: Song, difficulty: Difficulty) -> bool:
        return len(song.composers) > 1

    return pred


@_register(TopicType.FEATURING)
def _featuring(value: FilterValue) -> Predicate:
    def pred(song: Song, difficulty: Difficulty) -> bool:
        return len(song.featuring) > 0

    return pred


@_register(TopicType.TIME_BELOW)
def _time_below(value: FilterValue) -> Predicate:
    threshold = cast(int, value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        return song.time <= threshold

    return pred


@_register(TopicType.TIME_ABOVE)
def _time_above(value: FilterValue) -> Predicate:
    threshold = cast(int, value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        return song.time >= threshold

    return pred


@_register(TopicType.VERSION)
def _version(value: FilterValue) -> Predicate:
    allowed = _chars(value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        return song.version in allowed

    return pred


@_register(TopicType.BOOK)
def _book(value: FilterValue) -> Predicate:
    allowed = _chars(value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        return song.book in allowed

    return pred


@_register(TopicType.SHELF)
def _shelf(value: FilterValue) -> Predicate:
    allowed = _chars(value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        return song.shelf in allowed

    return pred
