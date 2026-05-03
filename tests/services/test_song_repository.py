"""
song_repository.py のユニットテスト

実 JSON (assets/data/all_songs.json) を用いたロード・部分一致検索・画像パス解決を検証します。
"""

import json
from pathlib import Path

import pytest

from src.services.song_repository import Song, SongRepository
from src.utils.helpers import get_absolute_path


# ==================================================
# fixtures
# ==================================================
@pytest.fixture
def real_songs_json() -> Path:
    """
    リポジトリ同梱の本物の all_songs.json
    """
    return get_absolute_path("assets/data/all_songs.json")


@pytest.fixture
def real_images_dir() -> Path:
    """
    リポジトリ同梱の本物の楽曲画像ディレクトリ
    """
    return get_absolute_path("assets/images")


@pytest.fixture
def real_repo(real_songs_json: Path, real_images_dir: Path) -> SongRepository:
    """
    実 JSON / 実画像ディレクトリを指す SongRepository
    """
    return SongRepository(songs_json=real_songs_json, images_dir=real_images_dir)


@pytest.fixture
def fake_repo(tmp_path: Path) -> SongRepository:
    """
    最小構成の独自 JSON を tmp_path に書き出してロードした SongRepository

    挙動を厳密に検証したいユニットテスト向けの fixture です。
    """
    data = {
        "ShelfA": {
            "BookA": {
                "Alpha Song": {
                    "VERSION": "1.0",
                    "LEVEL": {"Easy": 1, "Normal": 4, "Hard": 8},
                    "NOTES": {"Easy": 100, "Normal": 200, "Hard": 300},
                    "TIME": 120,
                    "COMPOSER": ["Composer A"],
                },
                "Beta Song": {
                    "VERSION": "1.5",
                    "LEVEL": {"Easy": 2, "Normal": 5, "Hard": 9, "Extra": 11},
                    "NOTES": {"Easy": 150, "Normal": 250, "Hard": 400, "Extra": 700},
                    "TIME": 180,
                    "COMPOSER": ["Composer B"],
                    "feat.": ["Vocalist B"],
                },
            },
        },
        "ShelfB": {
            "BookB": {
                "alpha twin": {
                    "VERSION": "2.0",
                    "LEVEL": {"Easy": 3, "Normal": 6, "Hard": 10},
                    "NOTES": {"Easy": 200, "Normal": 350, "Hard": 500},
                    "TIME": 200,
                    "COMPOSER": ["Composer C", "Composer D"],
                },
            },
        },
    }
    songs_json = tmp_path / "songs.json"
    songs_json.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    images_dir = tmp_path / "images"
    images_dir.mkdir()
    # Alpha Song のみ画像を実在させる (image_exists のテスト用)
    (images_dir / "Alpha Song.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    return SongRepository(songs_json=songs_json, images_dir=images_dir)


# ==================================================
# Song データクラス
# ==================================================
class TestSong:
    """
    Song データクラスのテスト
    """

    def test_construct_with_required_only(self):
        """
        feat / levels / notes 省略時はデフォルト (空コンテナ) になる
        """
        song = Song(
            name="X",
            shelf="S",
            book="B",
            version="1.0",
            time=100,
            composer=["C"],
        )
        assert song.feat == []
        assert song.levels == {}
        assert song.notes == {}

    def test_construct_with_all_fields(self):
        """
        全フィールド指定で正しく生成される
        """
        song = Song(
            name="X",
            shelf="S",
            book="B",
            version="2.0",
            time=120,
            composer=["C1", "C2"],
            feat=["F1"],
            levels={"Easy": 1, "Hard": 8},
            notes={"Easy": 100, "Hard": 500},
        )
        assert song.name == "X"
        assert song.composer == ["C1", "C2"]
        assert song.feat == ["F1"]
        assert song.levels["Hard"] == 8
        assert song.notes["Easy"] == 100


# ==================================================
# SongRepository - 実 JSON によるロード
# ==================================================
class TestSongRepositoryRealJson:
    """
    本物の all_songs.json を用いたロード検証
    """

    def test_load_real_json_count(self, real_repo: SongRepository):
        """
        実 JSON から 447 曲がロードされる (現時点のスナップショット)
        """
        assert len(real_repo) == 447
        assert len(real_repo.all()) == 447

    def test_load_real_json_known_song(self, real_repo: SongRepository):
        """
        既知曲 'Dream' のフィールドが正しく展開される
        """
        song = real_repo.find_by_name("Dream")
        assert song is not None
        assert song.shelf == "Story"
        assert song.book == "Deemo's collection Vol.1A"
        assert song.version == "1.0"
        assert song.time == 133
        assert song.composer == ["Rabpit"]
        assert song.feat == []
        assert song.levels == {"Easy": 1, "Normal": 4, "Hard": 8}
        assert song.notes == {"Easy": 78, "Normal": 313, "Hard": 485}

    def test_load_real_json_with_feat(self, real_repo: SongRepository):
        """
        feat. を持つ曲 ('Light pollution') では feat フィールドが設定される
        """
        song = real_repo.find_by_name("Light pollution")
        assert song is not None
        assert song.feat == ["Europa Huang"]

    def test_real_image_exists_for_known_song(self, real_repo: SongRepository):
        """
        実画像ディレクトリに存在する楽曲 (Aya) で image_exists が True を返す
        """
        assert real_repo.image_exists("Aya") is True
        assert real_repo.get_image_path("Aya").name == "Aya.png"


# ==================================================
# SongRepository - 検索 / 画像パス解決
# ==================================================
class TestSongRepositorySearchAndImage:
    """
    部分一致検索と画像パス解決の挙動を、独自 fixture (fake_repo) で厳密に検証
    """

    # --- find_by_name ---
    def test_find_by_name_exact_match(self, fake_repo: SongRepository):
        """
        完全一致で楽曲が取得できる
        """
        song = fake_repo.find_by_name("Alpha Song")
        assert song is not None
        assert song.name == "Alpha Song"

    def test_find_by_name_not_found(self, fake_repo: SongRepository):
        """
        存在しない名前なら None
        """
        assert fake_repo.find_by_name("Nonexistent") is None

    def test_find_by_name_is_case_sensitive(self, fake_repo: SongRepository):
        """
        find_by_name は完全一致のため、大文字小文字が異なれば None
        """
        assert fake_repo.find_by_name("alpha song") is None

    # --- search_partial ---
    def test_search_partial_case_insensitive(self, fake_repo: SongRepository):
        """
        部分一致は大文字小文字を区別せず、'alpha' で 2 件にマッチする
        """
        results = fake_repo.search_partial("alpha")
        names = {s.name for s in results}
        assert names == {"Alpha Song", "alpha twin"}

    def test_search_partial_partial_substring(self, fake_repo: SongRepository):
        """
        部分文字列が中央にあってもマッチする
        """
        results = fake_repo.search_partial("ong")
        names = {s.name for s in results}
        assert names == {"Alpha Song", "Beta Song"}

    def test_search_partial_no_match(self, fake_repo: SongRepository):
        """
        マッチしない場合は空リスト
        """
        assert fake_repo.search_partial("zzz") == []

    def test_search_partial_empty_query_returns_all(self, fake_repo: SongRepository):
        """
        空クエリは全件 (上限まで) を返す
        """
        results = fake_repo.search_partial("")
        assert len(results) == len(fake_repo)

    def test_search_partial_respects_limit(self, fake_repo: SongRepository):
        """
        limit 引数で件数が絞られる
        """
        results = fake_repo.search_partial("", limit=1)
        assert len(results) == 1

    def test_search_partial_default_limit_25(self, real_repo: SongRepository):
        """
        デフォルト limit (25) を超える結果は切り詰められる
        """
        results = real_repo.search_partial("a")
        assert len(results) == SongRepository.AUTOCOMPLETE_LIMIT

    def test_search_partial_invalid_limit(self, fake_repo: SongRepository):
        """
        limit が 1 未満の場合は ValueError
        """
        with pytest.raises(ValueError):
            fake_repo.search_partial("a", limit=0)

    # --- get_image_path / image_exists ---
    def test_get_image_path_format(self, fake_repo: SongRepository, tmp_path: Path):
        """
        画像パスは <images_dir>/<song_name>.png の形式
        """
        path = fake_repo.get_image_path("Alpha Song")
        assert path == tmp_path / "images" / "Alpha Song.png"

    def test_get_image_path_does_not_check_existence(
        self, fake_repo: SongRepository
    ):
        """
        get_image_path はファイル実在を検証せず、パス文字列のみを返す
        """
        path = fake_repo.get_image_path("Nonexistent Song")
        assert path.name == "Nonexistent Song.png"

    def test_image_exists_true(self, fake_repo: SongRepository):
        """
        実在する画像で True
        """
        assert fake_repo.image_exists("Alpha Song") is True

    def test_image_exists_false(self, fake_repo: SongRepository):
        """
        存在しない画像で False
        """
        assert fake_repo.image_exists("Beta Song") is False


# ==================================================
# SongRepository - エラーハンドリング
# ==================================================
class TestSongRepositoryErrors:
    """
    エラーハンドリングの検証
    """

    def test_load_missing_file_raises(self, tmp_path: Path):
        """
        JSON ファイルが存在しない場合は FileNotFoundError
        """
        missing = tmp_path / "missing.json"
        with pytest.raises(FileNotFoundError):
            SongRepository(songs_json=missing, images_dir=tmp_path)

    def test_load_missing_required_field_raises(self, tmp_path: Path):
        """
        必須フィールドが欠落していれば ValueError
        """
        data = {
            "S": {
                "B": {
                    "Broken": {
                        "VERSION": "1.0",
                        # LEVEL 欠落
                        "NOTES": {"Easy": 1},
                        "TIME": 1,
                        "COMPOSER": ["x"],
                    }
                }
            }
        }
        songs_json = tmp_path / "songs.json"
        songs_json.write_text(json.dumps(data), encoding="utf-8")

        with pytest.raises(ValueError, match="必須フィールド"):
            SongRepository(songs_json=songs_json, images_dir=tmp_path)
