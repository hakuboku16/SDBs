from __future__ import annotations

from collections.abc import Callable
from typing import cast

from src.game.models import Difficulty, FilterValue, Song, TopicType

Predicate = Callable[[Song, Difficulty], bool]
PredicateBuilder = Callable[[FilterValue], Predicate]

PREDICATE_BUILDERS: dict[TopicType, PredicateBuilder] = {}


def _register(topic_type: TopicType) -> Callable[[PredicateBuilder], PredicateBuilder]:
    """ビルダーを PREDICATE_BUILDERS へ自己登録するデコレータを返す。

    Args:
        topic_type: 登録先のお題型。

    Returns:
        Callable[[PredicateBuilder], PredicateBuilder]: ビルダーを登録して素通しするデコレータ。
    """
    # 中央の辞書リテラルを編集せず型ごとに自己登録させ、型の追加を局所化する。
    def deco(builder: PredicateBuilder) -> PredicateBuilder:
        """ビルダーを登録し、そのまま返す。"""
        PREDICATE_BUILDERS[topic_type] = builder
        return builder

    return deco


def _chars(value: FilterValue) -> tuple[str, ...]:
    """candidate 系の解決値を文字タプルへ絞り込む。

    Args:
        value: 解決済みフィルタ値(candidate 系の文字タプルを想定)。

    Returns:
        tuple[str, ...]: 文字タプルへキャストした値。
    """
    return cast(tuple[str, ...], value)


@_register(TopicType.TITLE_INCLUDE)
def _title_include(value: FilterValue) -> Predicate:
    """指定文字をすべて曲名に含むかの述語を作る。

    Args:
        value: 含むべき文字の組。

    Returns:
        Predicate: 曲名が全文字を含めば True を返す述語。
    """
    chars = _chars(value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        """曲名が指定文字をすべて含むか判定する。"""
        title = song.title.casefold()
        return all(ch in title for ch in chars)

    return pred


@_register(TopicType.TITLE_STARTSWITH)
def _title_startswith(value: FilterValue) -> Predicate:
    """曲名が指定文字で始まるかの述語を作る。

    Args:
        value: 先頭に一致させる文字の組。

    Returns:
        Predicate: 曲名がいずれかの文字で始まれば True を返す述語。
    """
    chars = _chars(value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        """曲名が指定文字で始まるか判定する。"""
        return song.title.casefold().startswith(chars)

    return pred


@_register(TopicType.TITLE_ENDSWITH)
def _title_endswith(value: FilterValue) -> Predicate:
    """曲名が指定文字で終わるかの述語を作る。

    Args:
        value: 末尾に一致させる文字の組。

    Returns:
        Predicate: 曲名がいずれかの文字で終われば True を返す述語。
    """
    chars = _chars(value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        """曲名が指定文字で終わるか判定する。"""
        return song.title.casefold().endswith(chars)

    return pred


@_register(TopicType.TITLE_LEN_BELOW)
def _title_len_below(value: FilterValue) -> Predicate:
    """曲名長が閾値以下かの述語を作る。

    Args:
        value: 上限となる文字数。

    Returns:
        Predicate: 曲名長が閾値以下なら True を返す述語。
    """
    threshold = cast(int, value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        """曲名長が閾値以下か判定する。"""
        return len(song.title) <= threshold

    return pred


@_register(TopicType.TITLE_LEN_ABOVE)
def _title_len_above(value: FilterValue) -> Predicate:
    """曲名長が閾値以上かの述語を作る。

    Args:
        value: 下限となる文字数。

    Returns:
        Predicate: 曲名長が閾値以上なら True を返す述語。
    """
    threshold = cast(int, value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        """曲名長が閾値以上か判定する。"""
        return len(song.title) >= threshold

    return pred


@_register(TopicType.TITLE_BLANK)
def _title_blank(value: FilterValue) -> Predicate:
    """曲名中の空白数が指定値と一致するかの述語を作る。

    Args:
        value: 一致させる空白数。

    Returns:
        Predicate: 曲名の空白数が一致すれば True を返す述語。
    """
    count = cast(int, value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        """曲名の空白数が指定値と一致するか判定する。"""
        return song.title.count(" ") == count

    return pred


@_register(TopicType.DIFFICULT)
def _difficult(value: FilterValue) -> Predicate:
    """申告難易度が許容集合に含まれるかの述語を作る。

    Args:
        value: 許容する難易度名の組。

    Returns:
        Predicate: 申告難易度が許容されていれば True を返す述語。
    """
    allowed = _chars(value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        """申告難易度が許容集合に含まれるか判定する。"""
        return difficulty.value in allowed

    return pred


@_register(TopicType.LEVEL)
def _level(value: FilterValue) -> Predicate:
    """指定レベルの譜面を持つかの述語を作る。

    Args:
        value: 一致させる譜面レベル。

    Returns:
        Predicate: いずれかの譜面が指定レベルなら True を返す述語。
    """
    level = cast(int, value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        """指定レベルの譜面を持つか判定する。"""
        # レベルが文字列(level=None)の Extra 譜面は数値比較できないため一致しない。
        return any(chart.level == level for chart in song.charts.values())

    return pred


def _always_true(value: FilterValue) -> Predicate:
    """常に True を返す述語を作る(SUM 型用)。

    Args:
        value: 使用しない(シグネチャ統一のため受け取る)。

    Returns:
        Predicate: 全プレイを対象にする常時 True の述語。
    """
    # SUM 型はフィルタを持たず全プレイを累積対象にする。
    def pred(song: Song, difficulty: Difficulty) -> bool:
        """常に True を返す。"""
        return True

    return pred


PREDICATE_BUILDERS[TopicType.LEVEL_TOTAL] = _always_true
PREDICATE_BUILDERS[TopicType.RESULT_COMBO_TOTAL] = _always_true
PREDICATE_BUILDERS[TopicType.RESULT_CHARMING_TOTAL] = _always_true


@_register(TopicType.NOTES_BELOW)
def _notes_below(value: FilterValue) -> Predicate:
    """ノーツ数が閾値以下の譜面を持つかの述語を作る。

    Args:
        value: 上限となるノーツ数。

    Returns:
        Predicate: いずれかの譜面が閾値以下なら True を返す述語。
    """
    threshold = cast(int, value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        """ノーツ数が閾値以下の譜面を持つか判定する。"""
        return any(chart.notes <= threshold for chart in song.charts.values())

    return pred


@_register(TopicType.NOTES_ABOVE)
def _notes_above(value: FilterValue) -> Predicate:
    """ノーツ数が閾値以上の譜面を持つかの述語を作る。

    Args:
        value: 下限となるノーツ数。

    Returns:
        Predicate: いずれかの譜面が閾値以上なら True を返す述語。
    """
    threshold = cast(int, value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        """ノーツ数が閾値以上の譜面を持つか判定する。"""
        return any(chart.notes >= threshold for chart in song.charts.values())

    return pred


@_register(TopicType.NOTES_DENSITY_BELOW)
def _notes_density_below(value: FilterValue) -> Predicate:
    """ノーツ密度が閾値以下の譜面を持つかの述語を作る。

    Args:
        value: 上限となるノーツ密度(notes / time)。

    Returns:
        Predicate: いずれかの譜面の密度が閾値以下なら True を返す述語。
    """
    threshold = cast(float, value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        """ノーツ密度が閾値以下の譜面を持つか判定する。"""
        return any(chart.notes / song.time <= threshold for chart in song.charts.values())

    return pred


@_register(TopicType.NOTES_DENSITY_ABOVE)
def _notes_density_above(value: FilterValue) -> Predicate:
    """ノーツ密度が閾値以上の譜面を持つかの述語を作る。

    Args:
        value: 下限となるノーツ密度(notes / time)。

    Returns:
        Predicate: いずれかの譜面の密度が閾値以上なら True を返す述語。
    """
    threshold = cast(float, value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        """ノーツ密度が閾値以上の譜面を持つか判定する。"""
        return any(chart.notes / song.time >= threshold for chart in song.charts.values())

    return pred


@_register(TopicType.NOTES_ENDSWITH)
def _notes_endswith(value: FilterValue) -> Predicate:
    """ノーツ数が指定数字で終わる譜面を持つかの述語を作る。

    Args:
        value: 末尾に一致させる数字文字列の組。

    Returns:
        Predicate: いずれかの譜面のノーツ数が指定数字で終われば True を返す述語。
    """
    digits = _chars(value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        """ノーツ数が指定数字で終わる譜面を持つか判定する。"""
        return any(str(chart.notes).endswith(digits) for chart in song.charts.values())

    return pred


@_register(TopicType.COMPOSER_NAME_STARTSWITH)
def _composer_name_startswith(value: FilterValue) -> Predicate:
    """作曲者名が指定文字で始まるかの述語を作る。

    Args:
        value: 先頭に一致させる文字の組。

    Returns:
        Predicate: いずれかの作曲者名が指定文字で始まれば True を返す述語。
    """
    chars = _chars(value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        """作曲者名が指定文字で始まるか判定する。"""
        return any(name.casefold().startswith(chars) for name in song.composers)

    return pred


@_register(TopicType.COMPOSER_NAME_ENDSWITH)
def _composer_name_endswith(value: FilterValue) -> Predicate:
    """作曲者名が指定文字で終わるかの述語を作る。

    Args:
        value: 末尾に一致させる文字の組。

    Returns:
        Predicate: いずれかの作曲者名が指定文字で終われば True を返す述語。
    """
    chars = _chars(value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        """作曲者名が指定文字で終わるか判定する。"""
        return any(name.casefold().endswith(chars) for name in song.composers)

    return pred


@_register(TopicType.COMPOSER_MEMBERS)
def _composer_members(value: FilterValue) -> Predicate:
    """作曲者が複数いるかの述語を作る。

    Args:
        value: 使用しない(シグネチャ統一のため受け取る)。

    Returns:
        Predicate: 作曲者が 2 人以上なら True を返す述語。
    """
    def pred(song: Song, difficulty: Difficulty) -> bool:
        """作曲者が複数いるか判定する。"""
        return len(song.composers) > 1

    return pred


@_register(TopicType.FEATURING)
def _featuring(value: FilterValue) -> Predicate:
    """featuring を持つかの述語を作る。

    Args:
        value: 使用しない(シグネチャ統一のため受け取る)。

    Returns:
        Predicate: featuring が 1 件以上なら True を返す述語。
    """
    def pred(song: Song, difficulty: Difficulty) -> bool:
        """featuring を持つか判定する。"""
        return len(song.featuring) > 0

    return pred


@_register(TopicType.TIME_BELOW)
def _time_below(value: FilterValue) -> Predicate:
    """曲の長さが閾値以下かの述語を作る。

    Args:
        value: 上限となる秒数。

    Returns:
        Predicate: 曲の長さが閾値以下なら True を返す述語。
    """
    threshold = cast(int, value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        """曲の長さが閾値以下か判定する。"""
        return song.time <= threshold

    return pred


@_register(TopicType.TIME_ABOVE)
def _time_above(value: FilterValue) -> Predicate:
    """曲の長さが閾値以上かの述語を作る。

    Args:
        value: 下限となる秒数。

    Returns:
        Predicate: 曲の長さが閾値以上なら True を返す述語。
    """
    threshold = cast(int, value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        """曲の長さが閾値以上か判定する。"""
        return song.time >= threshold

    return pred


@_register(TopicType.VERSION)
def _version(value: FilterValue) -> Predicate:
    """曲のバージョンが許容集合に含まれるかの述語を作る。

    Args:
        value: 許容するバージョン名の組。

    Returns:
        Predicate: バージョンが許容されていれば True を返す述語。
    """
    allowed = _chars(value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        """曲のバージョンが許容集合に含まれるか判定する。"""
        return song.version in allowed

    return pred


@_register(TopicType.BOOK)
def _book(value: FilterValue) -> Predicate:
    """曲の book が許容集合に含まれるかの述語を作る。

    Args:
        value: 許容する book 名の組。

    Returns:
        Predicate: book が許容されていれば True を返す述語。
    """
    allowed = _chars(value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        """曲の book が許容集合に含まれるか判定する。"""
        return song.book in allowed

    return pred


@_register(TopicType.SHELF)
def _shelf(value: FilterValue) -> Predicate:
    """曲の shelf が許容集合に含まれるかの述語を作る。

    Args:
        value: 許容する shelf 名の組。

    Returns:
        Predicate: shelf が許容されていれば True を返す述語。
    """
    allowed = _chars(value)

    def pred(song: Song, difficulty: Difficulty) -> bool:
        """曲の shelf が許容集合に含まれるか判定する。"""
        return song.shelf in allowed

    return pred
