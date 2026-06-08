from __future__ import annotations

from collections.abc import Callable

from src.game.models import (
    Chart,
    PlayCondition,
    PlayReport,
    ProgressKind,
    Topic,
    TopicType,
)
from src.game.predicates import PREDICATE_BUILDERS

# SUM 型ごとの累積値。COUNT 型は対象外(常に +1 のため登録しない)。
_SUM_VALUE_EXTRACTORS: dict[TopicType, Callable[[PlayReport, Chart], int]] = {
    TopicType.LEVEL_TOTAL: lambda report, chart: chart.level,
    TopicType.RESULT_COMBO_TOTAL: lambda report, chart: report.combo,
    TopicType.RESULT_CHARMING_TOTAL: lambda report, chart: report.charming,
}


def _play_condition_met(condition: PlayCondition, report: PlayReport, chart: Chart) -> bool:
    # FC/AC は申告 combo/charming が当該難易度の総ノーツ数に一致するかで判定する。
    if condition is PlayCondition.PLAY:
        return True
    if condition is PlayCondition.FULL_COMBO:
        return report.combo == chart.notes
    return report.combo == chart.notes and report.charming == chart.notes


def apply_report(report: PlayReport, topics: list[Topic]) -> list[Topic]:
    # 申告難易度の譜面が無い曲は FC/AC 判定も SUM 抽出もできないため照合せずスキップ。
    chart = report.song.charts.get(report.difficulty)
    if chart is None:
        return []
    newly_completed: list[Topic] = []
    for topic in topics:
        if topic.completed:
            continue
        predicate = PREDICATE_BUILDERS[topic.topic_type](topic.filter_value)
        if not predicate(report.song, report.difficulty):
            continue
        if not _play_condition_met(topic.play_condition, report, chart):
            continue
        if topic.progress_kind is ProgressKind.SUM:
            topic.progress += _SUM_VALUE_EXTRACTORS[topic.topic_type](report, chart)
        else:
            topic.progress += 1
        if topic.progress >= topic.required:
            topic.completed = True
            newly_completed.append(topic)
    return newly_completed
