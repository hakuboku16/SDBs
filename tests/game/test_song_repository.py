from pathlib import Path

from src.game.models import Difficulty
from src.game.song_repository import load_songs


def test_load_parses_basic_fields(song_assets: tuple[Path, Path]) -> None:
    songs_path, images_dir = song_assets
    by_title = {s.title: s for s in load_songs(songs_path, images_dir)}
    dream = by_title["Dream"]
    assert dream.shelf == "Story"
    assert dream.book == "Deemo's collection Vol.1A"
    assert dream.version == "1.0"
    assert dream.time == 133
    assert dream.composers == ("Rabpit",)


def test_featuring_detected(song_assets: tuple[Path, Path]) -> None:
    songs_path, images_dir = song_assets
    by_title = {s.title: s for s in load_songs(songs_path, images_dir)}
    assert by_title["Pulses"].featuring == ("A",)
    assert by_title["Dream"].featuring == ()


def test_multiple_composers(song_assets: tuple[Path, Path]) -> None:
    songs_path, images_dir = song_assets
    by_title = {s.title: s for s in load_songs(songs_path, images_dir)}
    assert by_title["Futarimiti"].composers == ("Morrigan", "Cranky")


def test_charts_built_and_missing_difficulty_skipped(
    song_assets: tuple[Path, Path],
) -> None:
    songs_path, images_dir = song_assets
    by_title = {s.title: s for s in load_songs(songs_path, images_dir)}
    dream = by_title["Dream"]
    assert dream.charts[Difficulty.HARD].notes == 485
    assert dream.charts[Difficulty.NORMAL].level == 4
    saika = by_title["Saika"]
    assert Difficulty.NORMAL not in saika.charts
    assert set(saika.charts) == {Difficulty.EASY, Difficulty.HARD}


def test_image_resolution(song_assets: tuple[Path, Path]) -> None:
    songs_path, images_dir = song_assets
    by_title = {s.title: s for s in load_songs(songs_path, images_dir)}
    assert by_title["Dream"].image_path == images_dir / "Dream.png"
    assert by_title["Pulses"].image_path is None
