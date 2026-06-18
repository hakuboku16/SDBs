from src.game.models import (
    Chart,
    Difficulty,
    PlayCondition,
    PlayReport,
    ProgressKind,
    Song,
    Topic,
    TopicType,
)
from src.game.play_matcher import apply_report


def _song(
    *,
    title: str = "Dream",
    charts: dict[Difficulty, Chart] | None = None,
    composers: tuple[str, ...] = ("Rabpit",),
) -> Song:
    if charts is None:
        charts = {Difficulty.HARD: Chart(level=8, notes=485)}
    return Song(
        title=title,
        shelf="Story",
        book="Vol.1A",
        version="1.0",
        charts=charts,
        time=133,
        composers=composers,
        featuring=(),
        image_path=None,
    )


def _report(
    *,
    song: Song | None = None,
    difficulty: Difficulty = Difficulty.HARD,
    combo: int = 485,
    charming: int = 485,
) -> PlayReport:
    return PlayReport(
        song=song if song is not None else _song(),
        difficulty=difficulty,
        combo=combo,
        charming=charming,
    )


def _topic(
    *,
    topic_type: TopicType = TopicType.TITLE_INCLUDE,
    play_condition: PlayCondition = PlayCondition.PLAY,
    filter_value: object = ("d",),
    required: int = 1,
    progress_kind: ProgressKind = ProgressKind.COUNT,
    panel_no: int = 1,
) -> Topic:
    return Topic(
        panel_no=panel_no,
        topic_type=topic_type,
        play_condition=play_condition,
        filter_value=filter_value,
        required=required,
        progress_kind=progress_kind,
        description="dummy",
    )


def test_count_increments_on_filter_match() -> None:
    topic = _topic(required=2)
    # 進捗が増えれば未達成でも該当お題として返す。
    assert apply_report(_report(), [topic]) == [topic]
    assert topic.progress == 1 and topic.completed is False
    newly = apply_report(_report(), [topic])
    assert topic.progress == 2 and topic.completed is True
    assert newly == [topic]


def test_no_progress_when_filter_unmatched() -> None:
    topic = _topic(filter_value=("z",), required=1)
    assert apply_report(_report(), [topic]) == []
    assert topic.progress == 0 and topic.completed is False


def test_full_combo_condition() -> None:
    topic = _topic(play_condition=PlayCondition.FULL_COMBO, required=1)
    # combo != notes(485) → 成立しない
    assert apply_report(_report(combo=400), [topic]) == []
    assert topic.progress == 0
    # combo == notes → 成立
    newly = apply_report(_report(combo=485), [topic])
    assert topic.completed is True and newly == [topic]


def test_all_charming_condition() -> None:
    topic = _topic(play_condition=PlayCondition.ALL_CHARMING, required=1)
    # combo == notes だが charming != notes → 成立しない
    assert apply_report(_report(combo=485, charming=400), [topic]) == []
    assert topic.progress == 0
    # combo == notes かつ charming == notes → 成立
    newly = apply_report(_report(combo=485, charming=485), [topic])
    assert topic.completed is True and newly == [topic]


def test_sum_level_total_accumulates_chart_level() -> None:
    topic = _topic(
        topic_type=TopicType.LEVEL_TOTAL,
        filter_value=None,
        required=16,
        progress_kind=ProgressKind.SUM,
    )
    apply_report(_report(), [topic])  # HARD chart level 8
    assert topic.progress == 8 and topic.completed is False
    newly = apply_report(_report(), [topic])
    assert topic.progress == 16 and topic.completed is True and newly == [topic]


def test_sum_combo_total_accumulates_combo() -> None:
    topic = _topic(
        topic_type=TopicType.RESULT_COMBO_TOTAL,
        filter_value=None,
        required=800,
        progress_kind=ProgressKind.SUM,
    )
    apply_report(_report(combo=485), [topic])
    assert topic.progress == 485
    newly = apply_report(_report(combo=485), [topic])
    assert topic.progress == 970 and topic.completed is True and newly == [topic]


def test_sum_charming_total_accumulates_charming() -> None:
    topic = _topic(
        topic_type=TopicType.RESULT_CHARMING_TOTAL,
        filter_value=None,
        required=400,
        progress_kind=ProgressKind.SUM,
    )
    apply_report(_report(charming=300), [topic])
    assert topic.progress == 300
    newly = apply_report(_report(charming=300), [topic])
    assert topic.progress == 600 and topic.completed is True and newly == [topic]


def test_sum_respects_play_condition() -> None:
    topic = _topic(
        topic_type=TopicType.LEVEL_TOTAL,
        play_condition=PlayCondition.FULL_COMBO,
        filter_value=None,
        required=8,
        progress_kind=ProgressKind.SUM,
    )
    # combo != notes → 累積しない
    assert apply_report(_report(combo=400), [topic]) == []
    assert topic.progress == 0
    # combo == notes → level を累積
    newly = apply_report(_report(combo=485), [topic])
    assert topic.progress == 8 and topic.completed is True and newly == [topic]


def test_level_total_skips_chart_with_none_level() -> None:
    # Extra 譜面のレベルが文字列(None)だと加算できないため進捗を増やさずスキップする。
    song = _song(charts={Difficulty.EXTRA: Chart(level=None, notes=900)})
    topic = _topic(
        topic_type=TopicType.LEVEL_TOTAL,
        filter_value=None,
        required=8,
        progress_kind=ProgressKind.SUM,
    )
    applied = apply_report(
        _report(song=song, difficulty=Difficulty.EXTRA, combo=900, charming=900),
        [topic],
    )
    assert applied == []
    assert topic.progress == 0 and topic.completed is False


def test_invalid_difficulty_is_skipped() -> None:
    # 曲は HARD 譜面のみ。EASY 申告は照合せずスキップ。
    song = _song(charts={Difficulty.HARD: Chart(level=8, notes=485)})
    topic = _topic(required=1)
    newly = apply_report(_report(song=song, difficulty=Difficulty.EASY), [topic])
    assert newly == []
    assert topic.progress == 0 and topic.completed is False


def test_completed_topic_is_not_reprogressed() -> None:
    topic = _topic(required=1)
    topic.progress = 1
    topic.completed = True
    newly = apply_report(_report(), [topic])
    assert newly == []
    assert topic.progress == 1


def test_one_report_progresses_multiple_topics() -> None:
    title_topic = _topic(topic_type=TopicType.TITLE_INCLUDE, filter_value=("d",), required=1, panel_no=1)
    level_topic = _topic(topic_type=TopicType.LEVEL, filter_value=8, required=1, panel_no=2)
    newly = apply_report(_report(), [title_topic, level_topic])
    assert title_topic.completed is True and level_topic.completed is True
    # Topic は frozen=False のため非ハッシュ。入力順走査で順序は決定的なのでリスト比較する。
    assert newly == [title_topic, level_topic]
