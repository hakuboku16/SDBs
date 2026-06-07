from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from src.game.models import FilterValue, PlayCondition, ProgressKind, TopicType

ValueFormatter = Callable[[FilterValue], str]


def _format_chars(value: FilterValue) -> str:
    # candidate 系の解決値。単一はそのまま、複数は説明用に "(a, b)" で並べる。
    chars = cast(tuple[str, ...], value)
    if len(chars) == 1:
        return chars[0]
    return "(" + ", ".join(chars) + ")"


def _format_scalar(value: FilterValue) -> str:
    return str(value)


@dataclass(frozen=True)
class TypeInfo:
    """型ごとの進捗種別と value 整形担当。"""

    progress_kind: ProgressKind
    value_formatter: ValueFormatter


_SUM_TYPES = {
    TopicType.LEVEL_TOTAL,
    TopicType.RESULT_COMBO_TOTAL,
    TopicType.RESULT_CHARMING_TOTAL,
}

_CHAR_TYPES = {
    TopicType.TITLE_INCLUDE,
    TopicType.TITLE_STARTSWITH,
    TopicType.TITLE_ENDSWITH,
    TopicType.DIFFICULT,
    TopicType.NOTES_ENDSWITH,
    TopicType.COMPOSER_NAME_STARTSWITH,
    TopicType.COMPOSER_NAME_ENDSWITH,
    TopicType.VERSION,
    TopicType.BOOK,
    TopicType.SHELF,
}


def _build_type_info() -> dict[TopicType, TypeInfo]:
    info: dict[TopicType, TypeInfo] = {}
    for topic_type in TopicType:
        progress_kind = ProgressKind.SUM if topic_type in _SUM_TYPES else ProgressKind.COUNT
        formatter = _format_chars if topic_type in _CHAR_TYPES else _format_scalar
        info[topic_type] = TypeInfo(progress_kind=progress_kind, value_formatter=formatter)
    return info


TYPE_INFO = _build_type_info()


def format_value(topic_type: TopicType, value: FilterValue) -> str:
    return TYPE_INFO[topic_type].value_formatter(value)


def format_description(
    *,
    topic_type: TopicType,
    description: str,
    value: FilterValue,
    required: int,
    play_condition: PlayCondition,
) -> str:
    # value→set→play の順で置換する。整形後の value/required は set/play を再導入しない。
    text = description
    if "value" in text:
        text = text.replace("value", format_value(topic_type, value))
    text = text.replace("set", str(required))
    return text.replace("play", play_condition.value)
