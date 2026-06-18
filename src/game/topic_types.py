from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from src.game.models import FilterValue, PlayCondition, ProgressKind, TopicType

ValueFormatter = Callable[[FilterValue], str]


def _format_chars(value: FilterValue) -> str:
    """candidate 系の解決値を説明用文字列へ整形する。

    Args:
        value: candidate 系の解決値(文字タプル)。

    Returns:
        str: 単一はそのまま、複数は "(a, b)" 形式の文字列。
    """
    # candidate 系の解決値。単一はそのまま、複数は説明用に "(a, b)" で並べる。
    chars = cast(tuple[str, ...], value)
    if len(chars) == 1:
        return chars[0]
    return "(" + ", ".join(chars) + ")"


def _format_scalar(value: FilterValue) -> str:
    """スカラ値を文字列へ整形する。

    Args:
        value: range 系などのスカラ解決値。

    Returns:
        str: str() による文字列表現。
    """
    return str(value)


@dataclass(frozen=True)
class TypeInfo:
    """型ごとの進捗種別と value 整形担当。"""

    progress_kind: ProgressKind
    value_formatter: ValueFormatter


# お題説明の "play" 置換語に埋める表示文字列。PLAY のみ日本語化し FC/AC は表記を維持する。
_PLAY_CONDITION_DISPLAY = {
    PlayCondition.PLAY: "プレイ",
    PlayCondition.FULL_COMBO: PlayCondition.FULL_COMBO.value,
    PlayCondition.ALL_CHARMING: PlayCondition.ALL_CHARMING.value,
}

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
    """全お題型の TypeInfo 索引を構築する。

    Returns:
        dict[TopicType, TypeInfo]: 型ごとの進捗種別と value 整形担当の索引。
    """
    info: dict[TopicType, TypeInfo] = {}
    for topic_type in TopicType:
        progress_kind = ProgressKind.SUM if topic_type in _SUM_TYPES else ProgressKind.COUNT
        formatter = _format_chars if topic_type in _CHAR_TYPES else _format_scalar
        info[topic_type] = TypeInfo(progress_kind=progress_kind, value_formatter=formatter)
    return info


TYPE_INFO = _build_type_info()


def format_value(topic_type: TopicType, value: FilterValue) -> str:
    """お題型に応じて value を説明用へ整形する。

    Args:
        topic_type: 整形担当を決めるお題型。
        value: 整形対象の解決済みフィルタ値。

    Returns:
        str: 型に対応した整形済み文字列。
    """
    return TYPE_INFO[topic_type].value_formatter(value)


def format_description(
    *,
    topic_type: TopicType,
    description: str,
    value: FilterValue,
    required: int,
    play_condition: PlayCondition,
) -> str:
    """説明テンプレートの置換語を解決値で埋める。

    Args:
        topic_type: value 整形に使うお題型。
        description: value/set/play の置換語を含むテンプレート文。
        value: value 置換語に埋める解決値。
        required: set 置換語に埋める必要回数。
        play_condition: play 置換語に埋めるプレイ種別。

    Returns:
        str: 置換語を解決した説明文。
    """
    # value→set→play の順で置換する。整形後の value/required は set/play を再導入しない。
    text = description
    if "value" in text:
        text = text.replace("value", format_value(topic_type, value))
    text = text.replace("set", str(required))
    return text.replace("play", _PLAY_CONDITION_DISPLAY[play_condition])
