from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from src.game.models import TopicType


@dataclass(frozen=True)
class RangeSpec:
    """[low, high, step] の閉区間から数値を抽選するための指定。"""

    low: float
    high: float
    step: float


@dataclass(frozen=True)
class CandidateSpec:
    """候補から choice 個選ぶ指定。candidate は文字プール/候補リスト/派生一覧トークン。"""

    candidate: str | tuple[str, ...]
    choice: int


ValueSpec = RangeSpec | CandidateSpec | None


@dataclass(frozen=True)
class TopicTemplate:
    """お題 1 型のテンプレート。"""

    topic_type: TopicType
    description: str
    set_spec: tuple[int, int, int]
    value_spec: ValueSpec


def _parse_value(raw: object) -> ValueSpec:
    if raw is None:
        return None
    node = cast(dict[str, object], raw)
    if "range" in node:
        low, high, step = cast(list[float], node["range"])
        return RangeSpec(low=low, high=high, step=step)
    candidate = node["candidate"]
    choice = cast(int, node["choice"])
    if isinstance(candidate, list):
        return CandidateSpec(candidate=tuple(cast(list[str], candidate)), choice=choice)
    return CandidateSpec(candidate=cast(str, candidate), choice=choice)


def load_topics(topics_path: Path) -> list[TopicTemplate]:
    raw = cast(list[dict[str, object]], json.loads(topics_path.read_text(encoding="utf-8")))
    templates: list[TopicTemplate] = []
    for node in raw:
        set_min, set_max, set_step = cast(list[int], node["set"])
        templates.append(
            TopicTemplate(
                topic_type=TopicType(cast(str, node["type"])),
                description=cast(str, node["description"]),
                set_spec=(set_min, set_max, set_step),
                value_spec=_parse_value(node.get("value")),
            )
        )
    return templates
