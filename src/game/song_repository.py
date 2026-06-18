from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import cast

from src.game.models import Chart, Difficulty, Song


def _normalize(text: str) -> str:
    """文字列を NFC 正規化する。

    Args:
        text: 正規化対象の文字列。

    Returns:
        str: NFC 正規化後の文字列。
    """
    # 曲名とファイル名で Unicode 表現(NFC/NFD)が食い違っても突合できるよう正規化する。
    return unicodedata.normalize("NFC", text)


def _build_image_index(images_dir: Path) -> dict[str, Path]:
    """画像ディレクトリから曲名→画像パスの索引を作る。

    Args:
        images_dir: PNG 画像が並ぶディレクトリ。存在しなければ空索引を返す。

    Returns:
        dict[str, Path]: 正規化したファイル名(拡張子なし)から画像パスへの索引。
    """
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
    """JSON ノード 1 件を Song へ変換する。

    Args:
        title: 曲名。
        book: 所属 book。
        shelf: 所属 shelf。
        node: 1 曲分の生 JSON ノード。
        image_index: 曲名→画像パスの索引。

    Returns:
        Song: 構築した楽曲データ。画像が無ければ image_path は None。
    """
    levels = cast(dict[str, object], node["LEVEL"])
    notes = cast(dict[str, int], node["NOTES"])
    charts: dict[Difficulty, Chart] = {}
    for difficulty in Difficulty:
        name = difficulty.value
        if name in levels and name in notes:
            # Extra 譜面はレベルが文字列の曲があるため、数値以外は None として取り込む。
            raw_level = levels[name]
            level = raw_level if isinstance(raw_level, int) else None
            charts[difficulty] = Chart(level=level, notes=notes[name])
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
    """楽曲 JSON と画像ディレクトリから全楽曲を読み込む。

    Args:
        songs_path: shelf/book/title 階層の楽曲 JSON ファイル。
        images_dir: ジャケット画像が並ぶディレクトリ。

    Returns:
        list[Song]: 読み込んだ全楽曲。
    """
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
        """楽曲群を保持して初期化する。

        Args:
            songs: 問い合わせ対象の楽曲群。
        """
        self._songs = songs

    @classmethod
    def from_files(cls, songs_path: Path, images_dir: Path) -> SongRepository:
        """楽曲 JSON と画像ディレクトリから生成する。

        Args:
            songs_path: 楽曲 JSON ファイル。
            images_dir: ジャケット画像が並ぶディレクトリ。

        Returns:
            SongRepository: 読み込んだ楽曲を保持するリポジトリ。
        """
        return cls(load_songs(songs_path, images_dir))

    @property
    def songs(self) -> list[Song]:
        """保持する全楽曲のコピーを返す。

        Returns:
            list[Song]: 内部リストを破壊しないための複製。
        """
        return list(self._songs)

    def search(self, query: str) -> list[Song]:
        """曲名の部分一致で楽曲を検索する。

        Args:
            query: 検索語。

        Returns:
            list[Song]: 曲名に query を部分一致で含む楽曲。
        """
        # 入力ゆれを吸収するため正規化+大文字小文字無視で部分一致させる。
        needle = _normalize(query).casefold()
        return [s for s in self._songs if needle in _normalize(s.title).casefold()]

    def find_exact(self, query: str) -> Song | None:
        """曲名が完全一致(正規化・大文字小文字無視)する曲を返す。

        Args:
            query: 照合する曲名。

        Returns:
            Song | None: 正規化後に曲名が一致する曲。無ければ None。
        """
        # 部分一致候補から一意に確定するため、正規化後の完全一致を別途提供する。
        needle = _normalize(query).casefold()
        for song in self._songs:
            if _normalize(song.title).casefold() == needle:
                return song
        return None

    def songs_with_image(self) -> list[Song]:
        """画像を持つ楽曲のみを返す。

        Returns:
            list[Song]: image_path が None でない楽曲。
        """
        return [s for s in self._songs if s.image_path is not None]

    def shelves(self) -> list[str]:
        """登場する shelf 名の一覧を返す。

        Returns:
            list[str]: 重複を除いてソートした shelf 名。
        """
        return sorted({s.shelf for s in self._songs})

    def books(self) -> list[str]:
        """登場する book 名の一覧を返す。

        Returns:
            list[str]: 重複を除いてソートした book 名。
        """
        return sorted({s.book for s in self._songs})

    def versions(self) -> list[str]:
        """登場するバージョン名の一覧を返す。

        Returns:
            list[str]: 重複を除いてソートしたバージョン名。
        """
        return sorted({s.version for s in self._songs})
