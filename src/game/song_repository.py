from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import cast

from src.game.models import Chart, Difficulty, Song


def _normalize(text: str) -> str:
    # 曲名とファイル名で Unicode 表現(NFC/NFD)が食い違っても突合できるよう正規化する。
    return unicodedata.normalize("NFC", text)


def _build_image_index(images_dir: Path) -> dict[str, Path]:
    index: dict[str, Path] = {}
    if images_dir.is_dir():
        for path in images_dir.glob("*.png"):
            index[_normalize(path.stem)] = path
    return index


def _parse_song(
    title: str,
    book: str,
    shelf: str,
    node: dict[str, object],
    image_index: dict[str, Path],
) -> Song:
    levels = cast(dict[str, int], node["LEVEL"])
    notes = cast(dict[str, int], node["NOTES"])
    charts: dict[Difficulty, Chart] = {}
    for difficulty in Difficulty:
        name = difficulty.value
        if name in levels and name in notes:
            charts[difficulty] = Chart(level=levels[name], notes=notes[name])
    return Song(
        title=title,
        shelf=shelf,
        book=book,
        version=str(node["VERSION"]),
        charts=charts,
        time=cast(int, node["TIME"]),
        composers=tuple(cast(list[str], node.get("COMPOSER", []))),
        featuring=tuple(cast(list[str], node.get("feat.", []))),
        image_path=image_index.get(_normalize(title)),
    )


def load_songs(songs_path: Path, images_dir: Path) -> list[Song]:
    raw = cast(
        dict[str, dict[str, dict[str, dict[str, object]]]],
        json.loads(songs_path.read_text(encoding="utf-8")),
    )
    image_index = _build_image_index(images_dir)
    songs: list[Song] = []
    for shelf, books in raw.items():
        for book, entries in books.items():
            for title, node in entries.items():
                songs.append(_parse_song(title, book, shelf, node, image_index))
    return songs


class SongRepository:
    """読み込んだ楽曲群への問い合わせを提供する。"""

    def __init__(self, songs: list[Song]) -> None:
        self._songs = songs

    @classmethod
    def from_files(cls, songs_path: Path, images_dir: Path) -> SongRepository:
        return cls(load_songs(songs_path, images_dir))

    @property
    def songs(self) -> list[Song]:
        return list(self._songs)

    def search(self, query: str) -> list[Song]:
        # 入力ゆれを吸収するため正規化+大文字小文字無視で部分一致させる。
        needle = _normalize(query).casefold()
        return [s for s in self._songs if needle in _normalize(s.title).casefold()]

    def songs_with_image(self) -> list[Song]:
        return [s for s in self._songs if s.image_path is not None]
