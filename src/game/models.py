from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class Difficulty(str, Enum):
    """譜面の難易度。値は all_songs.json の LEVEL/NOTES のキーと一致させる。"""

    EASY = "Easy"
    NORMAL = "Normal"
    HARD = "Hard"


@dataclass(frozen=True)
class Chart:
    """1 つの難易度に対する譜面情報。"""

    level: int
    notes: int


@dataclass(frozen=True)
class Song:
    """1 楽曲のマスターデータ。"""

    title: str
    shelf: str
    book: str
    version: str
    charts: dict[Difficulty, Chart]
    time: int
    composers: tuple[str, ...]
    featuring: tuple[str, ...]
    image_path: Path | None


class TopicType(str, Enum):
    """お題テンプレートの型。値は all_topics.json の type と一致させる。"""

    TITLE_INCLUDE = "title_include"
    TITLE_STARTSWITH = "title_startswith"
    TITLE_ENDSWITH = "title_endswith"
    TITLE_LEN_BELOW = "title_len_below"
    TITLE_LEN_ABOVE = "title_len_above"
    TITLE_BLANK = "title_blank"
    DIFFICULT = "difficult"
    LEVEL = "level"
    LEVEL_TOTAL = "level_total"
    RESULT_CHARMING_TOTAL = "result_charming_total"
    RESULT_COMBO_TOTAL = "result_combo_total"
    NOTES_BELOW = "notes_below"
    NOTES_ABOVE = "notes_above"
    NOTES_DENSITY_BELOW = "notes_density_below"
    NOTES_DENSITY_ABOVE = "notes_density_above"
    NOTES_ENDSWITH = "notes_endswith"
    COMPOSER_NAME_STARTSWITH = "composer_name_startswith"
    COMPOSER_NAME_ENDSWITH = "composer_name_endswith"
    COMPOSER_MEMBERS = "composer_members"
    FEATURING = "featuring"
    TIME_BELOW = "time_below"
    TIME_ABOVE = "time_above"
    VERSION = "version"
    BOOK = "book"
    SHELF = "shelf"


class PlayCondition(str, Enum):
    """お題達成に要するプレイ種別。値は説明文の置換語にも使う。"""

    PLAY = "play"
    FULL_COMBO = "FC"
    ALL_CHARMING = "AC"


class ProgressKind(str, Enum):
    """進捗の数え方。COUNT=条件一致プレイの回数、SUM=申告値の累積。"""

    COUNT = "COUNT"
    SUM = "SUM"


# 解決済みフィルタ値。candidate 系は選んだ文字/候補の組、range 系は数値、null 型は None。
FilterValue = tuple[str, ...] | int | float | None


@dataclass
class Topic:
    """生成済みの 1 お題。progress/completed はプレイ進行で更新するため frozen にしない。"""

    panel_no: int
    topic_type: TopicType
    play_condition: PlayCondition
    filter_value: FilterValue
    required: int
    progress_kind: ProgressKind
    description: str
    progress: int = 0
    completed: bool = False
