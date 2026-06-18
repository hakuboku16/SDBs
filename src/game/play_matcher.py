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
# LEVEL_TOTAL は Extra 譜面のレベルが文字列(level=None)だと加算できず None を返す。
_SUM_VALUE_EXTRACTORS: dict[TopicType, Callable[[PlayReport, Chart], int | None]] = {
    TopicType.LEVEL_TOTAL: lambda report, chart: chart.level,
    TopicType.RESULT_COMBO_TOTAL: lambda report, chart: report.combo,
    TopicType.RESULT_CHARMING_TOTAL: lambda report, chart: report.charming,
}


def _play_condition_met(condition: PlayCondition, report: PlayReport, chart: Chart) -> bool:
    """プレイ種別の条件を申告が満たすか判定する。

    Args:
        condition: お題が要求するプレイ種別。
        report: プレイ申告 1 件。
        chart: 申告難易度の譜面情報。

    Returns:
        bool: 条件を満たせば True。PLAY は常に True。
    """
    # FC/AC は申告 combo/charming が当該難易度の総ノーツ数に一致するかで判定する。
    if condition is PlayCondition.PLAY:
        return True
    if condition is PlayCondition.FULL_COMBO:
        return report.combo == chart.notes
    return report.combo == chart.notes and report.charming == chart.notes


def apply_report(report: PlayReport, topics: list[Topic]) -> list[Topic]:
    """プレイ申告を全お題へ照合し、進捗を更新して該当したお題を返す。

    Args:
        report: プレイ申告 1 件。
        topics: 進捗を更新する対象のお題群。要素は破壊的に更新される。

    Returns:
        list[Topic]: この申告で進捗が増えた(該当した)お題。各要素の completed が
            True ならこの申告で新規達成したことを表す。申告難易度の譜面が無い曲は空。
    """
    # 申告難易度の譜面が無い曲は FC/AC 判定も SUM 抽出もできないため照合せずスキップ。
    chart = report.song.charts.get(report.difficulty)
    if chart is None:
        return []
    applied: list[Topic] = []
    for topic in topics:
        if topic.completed:
            continue
        predicate = PREDICATE_BUILDERS[topic.topic_type](topic.filter_value)
        if not predicate(report.song, report.difficulty):
            continue
        if not _play_condition_met(topic.play_condition, report, chart):
            continue
        if topic.progress_kind is ProgressKind.SUM:
            value = _SUM_VALUE_EXTRACTORS[topic.topic_type](report, chart)
            # Extra 譜面のレベルが文字列で数値化できない場合は加算せずスキップする。
            if value is None:
                continue
            topic.progress += value
        else:
            topic.progress += 1
        if topic.progress >= topic.required:
            topic.completed = True
        applied.append(topic)
    return applied
