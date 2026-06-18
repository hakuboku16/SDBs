from src.game.models import PlayCondition, ProgressKind, TopicType
from src.game.topic_types import TYPE_INFO, format_description, format_value


def test_all_types_have_info() -> None:
    assert set(TYPE_INFO) == set(TopicType)


def test_sum_progress_kinds() -> None:
    sum_types = {
        TopicType.LEVEL_TOTAL,
        TopicType.RESULT_COMBO_TOTAL,
        TopicType.RESULT_CHARMING_TOTAL,
    }
    for topic_type in TopicType:
        expected = ProgressKind.SUM if topic_type in sum_types else ProgressKind.COUNT
        assert TYPE_INFO[topic_type].progress_kind is expected


def test_format_value_variants() -> None:
    assert format_value(TopicType.TITLE_INCLUDE, ("a", "c")) == "(a, c)"
    assert format_value(TopicType.NOTES_ENDSWITH, ("0",)) == "0"
    assert format_value(TopicType.DIFFICULT, ("Hard",)) == "Hard"
    assert format_value(TopicType.LEVEL, 8) == "8"
    assert format_value(TopicType.NOTES_DENSITY_ABOVE, 1.2) == "1.2"


def test_format_description_replaces_tokens() -> None:
    text = format_description(
        topic_type=TopicType.TITLE_INCLUDE,
        description="楽曲名にvalueのすべてが含まれる楽曲をset回play",
        value=("a", "c"),
        required=3,
        play_condition=PlayCondition.FULL_COMBO,
    )
    assert text == "楽曲名に(a, c)のすべてが含まれる楽曲を3回FC"


def test_format_description_sum_without_value_token() -> None:
    text = format_description(
        topic_type=TopicType.LEVEL_TOTAL,
        description="playした譜面のレベルの合計がset",
        value=None,
        required=40,
        play_condition=PlayCondition.PLAY,
    )
    # PLAY は「プレイ」と日本語表記する(FC/AC は表記を維持)。
    assert text == "プレイした譜面のレベルの合計が40"


def test_format_description_play_condition_display_variants() -> None:
    # FC/AC は値そのまま、PLAY のみ日本語化する。
    assert (
        format_description(
            topic_type=TopicType.LEVEL_TOTAL,
            description="playした",
            value=None,
            required=1,
            play_condition=PlayCondition.ALL_CHARMING,
        )
        == "ACした"
    )
