"""
楽曲データのドメインモデルとリポジトリを提供するモジュール

`assets/data/all_songs.json` をロードし、楽曲の検索・画像パス解決を提供します。
JSON のネスト構造 (shelf -> book -> song -> 詳細) を、フラットな `Song` インスタンス群に展開します。
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ==================================================
# データ格納用クラス
# ==================================================
@dataclass
class Song:
    """
    Deemo の楽曲 1 件分を表すデータクラス

    JSON 上のネスト構造を展開し、shelf / book を含む全ての検索対象フィールドを保持します。
    難易度別の `levels` / `notes` は難易度名 (Easy / Normal / Hard / Extra) をキーとした辞書です。
    """

    name: str
    shelf: str
    book: str
    version: str
    time: int
    composer: list[str]
    feat: list[str] = field(default_factory=list)
    levels: dict[str, int] = field(default_factory=dict)
    notes: dict[str, int] = field(default_factory=dict)


# ==================================================
# リポジトリ
# ==================================================
class SongRepository:
    """
    楽曲データを保持し、検索および画像パス解決を提供するリポジトリ

    インスタンス生成時に JSON を一度だけロードしてオンメモリに展開します。
    """

    # Discord のオートコンプリートが返せる最大件数
    AUTOCOMPLETE_LIMIT: int = 25

    def __init__(self, songs_json: Path, images_dir: Path) -> None:
        """
        リポジトリを初期化し、JSON をロードする

        Args:
            songs_json: 楽曲メタデータ JSON ファイルへのパス
            images_dir: 楽曲ジャケット画像のディレクトリへのパス

        Raises:
            FileNotFoundError: songs_json が存在しない場合
            ValueError: JSON 構造が想定外の場合
        """
        self._songs_json: Path = songs_json
        self._images_dir: Path = images_dir
        self._songs: list[Song] = self._load(songs_json)
        self._by_name: dict[str, Song] = {song.name: song for song in self._songs}

    @staticmethod
    def _load(songs_json: Path) -> list[Song]:
        """
        JSON を読み込み、`Song` のリストに展開する

        Args:
            songs_json: 楽曲メタデータ JSON ファイルへのパス

        Returns:
            すべての楽曲を表す `Song` のリスト

        Raises:
            FileNotFoundError: ファイルが存在しない場合
            ValueError: 必須フィールドが欠落している場合
        """
        if not songs_json.is_file():
            raise FileNotFoundError(f"楽曲データが見つかりません: {songs_json}")

        with open(songs_json, "r", encoding="utf-8") as f:
            data: dict[str, dict[str, dict[str, dict]]] = json.load(f)

        songs: list[Song] = []
        for shelf_name, books in data.items():
            for book_name, book_songs in books.items():
                for song_name, info in book_songs.items():
                    songs.append(
                        SongRepository._build_song(
                            shelf=shelf_name,
                            book=book_name,
                            name=song_name,
                            info=info,
                        )
                    )
        return songs

    @staticmethod
    def _build_song(shelf: str, book: str, name: str, info: dict) -> Song:
        """
        単一楽曲の生 dict から `Song` を構築する

        Raises:
            ValueError: 必須フィールド (VERSION / LEVEL / NOTES / TIME / COMPOSER) が欠落している場合
        """
        required_keys = ("VERSION", "LEVEL", "NOTES", "TIME", "COMPOSER")
        missing = [k for k in required_keys if k not in info]
        if missing:
            raise ValueError(
                f"楽曲 '{name}' (shelf={shelf}, book={book}) に必須フィールドがありません: {missing}"
            )

        return Song(
            name=name,
            shelf=shelf,
            book=book,
            version=str(info["VERSION"]),
            time=int(info["TIME"]),
            composer=list(info["COMPOSER"]),
            feat=list(info.get("feat.", [])),
            levels=dict(info["LEVEL"]),
            notes=dict(info["NOTES"]),
        )

    # --------------------------------------------------
    # 取得・検索
    # --------------------------------------------------
    def all(self) -> list[Song]:
        """
        全楽曲のリスト (コピー) を返す
        """
        return list(self._songs)

    def __len__(self) -> int:
        return len(self._songs)

    def find_by_name(self, name: str) -> Optional[Song]:
        """
        楽曲名 (完全一致) で検索する

        Args:
            name: 楽曲名

        Returns:
            該当楽曲。見つからなければ None
        """
        return self._by_name.get(name)

    def search_partial(
        self, query: str, limit: int = AUTOCOMPLETE_LIMIT
    ) -> list[Song]:
        """
        楽曲名の部分一致 (大文字小文字を無視) で検索する

        空クエリの場合は全件 (上限 `limit` まで) を返します。
        Discord のオートコンプリート利用を想定し、デフォルト上限は 25 件です。

        Args:
            query: 検索文字列
            limit: 返却する最大件数 (1 以上)

        Returns:
            該当楽曲のリスト

        Raises:
            ValueError: limit が 1 未満の場合
        """
        if limit < 1:
            raise ValueError(f"limit は 1 以上の整数で指定してください: {limit}")

        if not query:
            return self._songs[:limit]

        q = query.casefold()
        matched: list[Song] = [
            song for song in self._songs if q in song.name.casefold()
        ]
        return matched[:limit]

    # --------------------------------------------------
    # 画像パス解決
    # --------------------------------------------------
    def get_image_path(self, song_name: str) -> Path:
        """
        楽曲名からジャケット画像パスを解決する (拡張子は `.png` 固定)

        画像ファイルの実在は検証しません。実在判定は `image_exists` を利用してください。

        Args:
            song_name: 楽曲名 (画像ファイル名から拡張子を除いたものと一致)

        Returns:
            画像ファイルへの絶対パス
        """
        return self._images_dir / f"{song_name}.png"

    def image_exists(self, song_name: str) -> bool:
        """
        楽曲名に対応するジャケット画像が存在するかを判定する
        """
        return self.get_image_path(song_name).is_file()
