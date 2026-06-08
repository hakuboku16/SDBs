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
    """RangeSpec の閉区間を step 刻みで列挙する。

    Args:
        spec: low/high/step を持つ数値範囲指定。

    Returns:
        list[int | float]: 範囲内の候補値。全て整数なら int 列、そうでなければ float 列。
    """
    count = round((spec.high - spec.low) / spec.step)
    values = [round(spec.low + i * spec.step, 6) for i in range(count + 1)]
    if all(float(v).is_integer() for v in values):
        return [int(v) for v in values]
    return values


def _candidate_pool(candidate: str | tuple[str, ...], repo: SongRepository) -> list[str]:
    """candidate 指定を抽選元の候補リストへ解決する。

    Args:
        candidate: 文字プール、候補タプル、または派生一覧トークン。
        repo: 派生一覧トークンの解決に使うリポジトリ。

    Returns:
        list[str]: 抽選元となる候補リスト。
    """
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
    """ValueSpec を 1 つの解決済みフィルタ値へ抽選する。

    Args:
        spec: range/candidate/None のいずれかの value 指定。
        repo: candidate 解決に使うリポジトリ。
        rng: 抽選に使う乱数生成器。

    Returns:
        FilterValue: range は単一数値、candidate はソート済み文字タプル、None 指定は None。
    """
    if spec is None:
        return None
    if isinstance(spec, RangeSpec):
        return rng.choice(_stepped_values(spec))
    pool = _candidate_pool(spec.candidate, repo)
    return tuple(sorted(rng.sample(pool, spec.choice)))


def _roll_required(set_spec: tuple[int, int, int], rng: random.Random) -> int:
    """必要回数を (min, max, step) から抽選する。

    Args:
        set_spec: 必要回数の (min, max, step)。
        rng: 抽選に使う乱数生成器。

    Returns:
        int: 抽選した必要回数。
    """
    set_min, set_max, set_step = set_spec
    return rng.choice(list(range(set_min, set_max + 1, set_step)))


def _roll_play_condition(rng: random.Random) -> PlayCondition:
    """プレイ種別を重み付きで抽選する。

    Args:
        rng: 抽選に使う乱数生成器。

    Returns:
        PlayCondition: PLAY 60% / FULL_COMBO 30% / ALL_CHARMING 10% で抽選した種別。
    """
    roll = rng.random()
    if roll < 0.6:
        return PlayCondition.PLAY
    if roll < 0.9:
        return PlayCondition.FULL_COMBO
    return PlayCondition.ALL_CHARMING


def _is_achievable(predicate: Predicate, songs: list[Song]) -> bool:
    """述語を満たす曲/難易度が 1 つでも存在するか判定する。

    Args:
        predicate: 判定する述語。
        songs: 走査対象の楽曲群。

    Returns:
        bool: いずれかの曲/難易度が述語を満たせば True。
    """
    return any(predicate(song, difficulty) for song in songs for difficulty in song.charts)


def generate_topic(
    template: TopicTemplate,
    panel_no: int,
    repo: SongRepository,
    rng: random.Random,
) -> Topic:
    """テンプレートから達成可能なお題を 1 件生成する。

    Args:
        template: 生成元のお題テンプレート。
        panel_no: 割り当てる盤面パネル番号。
        repo: value 解決と達成可能性判定に使うリポジトリ。
        rng: 抽選に使う乱数生成器。

    Returns:
        Topic: 生成した達成可能なお題。

    Raises:
        RuntimeError: 規定試行回数内に達成可能なお題を生成できなかった場合。
    """
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
    """生成元テンプレートを count 個選ぶ。

    Args:
        templates: 選択元のテンプレート群。
        count: 選ぶ個数。
        rng: 抽選に使う乱数生成器。

    Returns:
        list[TopicTemplate]: 選んだテンプレート。型数以下なら重複なし、超過分は重複を許す。
    """
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
    """テンプレート群から count 個のお題を生成する。

    Args:
        templates: 生成元のテンプレート群。
        count: 生成するお題数。
        repo: value 解決と達成可能性判定に使うリポジトリ。
        rng: 抽選に使う乱数生成器。

    Returns:
        list[Topic]: panel_no を 1 から振った生成済みお題。
    """
    chosen = _choose_templates(templates, count, rng)
    return [
        generate_topic(template, panel_no=index + 1, repo=repo, rng=rng)
        for index, template in enumerate(chosen)
    ]
