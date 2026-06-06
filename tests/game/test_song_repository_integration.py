from pathlib import Path

from src.game.song_repository import SongRepository

ASSETS = Path(__file__).resolve().parents[2] / "assets"


def test_real_master_data_loads() -> None:
    repo = SongRepository.from_files(
        ASSETS / "data" / "all_songs.json",
        ASSETS / "images",
    )
    titles = {s.title for s in repo.songs}
    assert len(titles) > 100
    assert "Dream" in titles
    assert "Story" in repo.shelves()

    dream = next(s for s in repo.songs if s.title == "Dream")
    assert dream.image_path is not None
    assert dream.image_path.exists()
    assert repo.songs_with_image()  # 画像が解決できる曲が存在する
