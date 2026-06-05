from src.game.models import Chart, Difficulty, Song


def test_song_construction() -> None:
    song = Song(
        title="Dream",
        shelf="Story",
        book="Deemo's collection Vol.1A",
        version="1.0",
        charts={Difficulty.HARD: Chart(level=8, notes=485)},
        time=133,
        composers=("Rabpit",),
        featuring=(),
        image_path=None,
    )
    assert song.charts[Difficulty.HARD].notes == 485
    assert song.featuring == ()
    assert Difficulty.EASY.value == "Easy"
