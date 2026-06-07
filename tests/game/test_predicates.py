from src.game.models import Chart, Difficulty, Song, TopicType
from src.game.predicates import PREDICATE_BUILDERS, FilterValue


def _song(
    *,
    title: str = "X",
    composers: tuple[str, ...] = ("C",),
    featuring: tuple[str, ...] = (),
    time: int = 100,
    version: str = "1.0",
    book: str = "B",
    shelf: str = "S",
    charts: dict[Difficulty, Chart] | None = None,
) -> Song:
    if charts is None:
        charts = {Difficulty.HARD: Chart(level=8, notes=485)}
    return Song(
        title=title,
        shelf=shelf,
        book=book,
        version=version,
        charts=charts,
        time=time,
        composers=composers,
        featuring=featuring,
        image_path=None,
    )


def _check(topic_type: TopicType, value: FilterValue, song: Song, difficulty: Difficulty) -> bool:
    return PREDICATE_BUILDERS[topic_type](value)(song, difficulty)


def test_all_types_registered() -> None:
    assert set(PREDICATE_BUILDERS) == set(TopicType)


def test_title_predicates() -> None:
    d = Difficulty.HARD
    assert _check(TopicType.TITLE_INCLUDE, ("a", "e"), _song(title="Daybreak"), d)
    assert not _check(TopicType.TITLE_INCLUDE, ("a", "z"), _song(title="Daybreak"), d)
    assert _check(TopicType.TITLE_STARTSWITH, ("a", "d"), _song(title="Dream"), d)
    assert not _check(TopicType.TITLE_STARTSWITH, ("x", "y"), _song(title="Dream"), d)
    assert _check(TopicType.TITLE_ENDSWITH, ("a", "k"), _song(title="Saika"), d)
    assert _check(TopicType.TITLE_LEN_BELOW, 5, _song(title="Aya"), d)
    assert not _check(TopicType.TITLE_LEN_BELOW, 2, _song(title="Aya"), d)
    assert _check(TopicType.TITLE_LEN_ABOVE, 3, _song(title="Aya"), d)
    assert _check(TopicType.TITLE_BLANK, 2, _song(title="a b c"), d)
    assert not _check(TopicType.TITLE_BLANK, 1, _song(title="a b c"), d)


def test_difficulty_and_level_predicates() -> None:
    charts = {
        Difficulty.EASY: Chart(level=1, notes=78),
        Difficulty.HARD: Chart(level=8, notes=485),
    }
    assert _check(TopicType.DIFFICULT, ("Hard",), _song(charts=charts), Difficulty.HARD)
    assert not _check(TopicType.DIFFICULT, ("Hard",), _song(charts=charts), Difficulty.EASY)
    assert _check(TopicType.LEVEL, 8, _song(charts=charts), Difficulty.EASY)
    assert not _check(TopicType.LEVEL, 12, _song(charts=charts), Difficulty.EASY)


def test_sum_predicates_always_true() -> None:
    d = Difficulty.HARD
    for topic_type in (
        TopicType.LEVEL_TOTAL,
        TopicType.RESULT_COMBO_TOTAL,
        TopicType.RESULT_CHARMING_TOTAL,
    ):
        assert _check(topic_type, None, _song(), d)


def test_notes_predicates() -> None:
    d = Difficulty.HARD
    song = _song(time=100, charts={Difficulty.HARD: Chart(level=8, notes=480)})
    assert _check(TopicType.NOTES_BELOW, 500, song, d)
    assert not _check(TopicType.NOTES_BELOW, 100, song, d)
    assert _check(TopicType.NOTES_ABOVE, 400, song, d)
    assert _check(TopicType.NOTES_DENSITY_BELOW, 5.0, song, d)  # 480/100=4.8
    assert _check(TopicType.NOTES_DENSITY_ABOVE, 4.0, song, d)
    assert _check(TopicType.NOTES_ENDSWITH, ("0",), song, d)  # 480 末尾 0
    assert not _check(TopicType.NOTES_ENDSWITH, ("5",), song, d)


def test_composer_predicates() -> None:
    d = Difficulty.HARD
    assert _check(TopicType.COMPOSER_NAME_STARTSWITH, ("s", "r"), _song(composers=("Rabpit",)), d)
    assert _check(TopicType.COMPOSER_NAME_ENDSWITH, ("t",), _song(composers=("Morrigan", "Rabpit")), d)
    assert _check(TopicType.COMPOSER_MEMBERS, None, _song(composers=("A", "B")), d)
    assert not _check(TopicType.COMPOSER_MEMBERS, None, _song(composers=("A",)), d)
    assert _check(TopicType.FEATURING, None, _song(featuring=("Singer",)), d)
    assert not _check(TopicType.FEATURING, None, _song(featuring=()), d)


def test_time_version_book_shelf_predicates() -> None:
    d = Difficulty.HARD
    song = _song(time=120, version="2.0", book="Etude", shelf="II")
    assert _check(TopicType.TIME_BELOW, 130, song, d)
    assert not _check(TopicType.TIME_BELOW, 100, song, d)
    assert _check(TopicType.TIME_ABOVE, 100, song, d)
    assert _check(TopicType.VERSION, ("1.0", "2.0"), song, d)
    assert not _check(TopicType.VERSION, ("1.0",), song, d)
    assert _check(TopicType.BOOK, ("Etude",), song, d)
    assert _check(TopicType.SHELF, ("II", "Story"), song, d)
