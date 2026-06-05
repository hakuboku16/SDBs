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
