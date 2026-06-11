from pathlib import Path

import pytest

from src.bot.game_service import AmbiguousSong, GameService, SongNotFound
from src.game.models import Chart, Difficulty, Song
from src.game.song_repository import SongRepository


def _song(title: str, *, image: bool = False) -> Song:
    """テスト用の最小 Song を組み立てる。

    Args:
        title: 曲名。
        image: 画像を持たせるか。True なら image_path にダミーパスを入れる。

    Returns:
        Song: 構築した楽曲。
    """
    return Song(
        title=title,
        shelf="Story",
        book="Vol.1A",
        version="1.0",
        charts={Difficulty.HARD: Chart(level=8, notes=485)},
        time=133,
        composers=("Rabpit",),
        featuring=(),
        image_path=Path("dummy.png") if image else None,
    )


def _service(songs: list[Song]) -> GameService:
    """指定楽曲を持つ GameService を組み立てる(テンプレートは空)。

    Args:
        songs: リポジトリへ載せる楽曲群。

    Returns:
        GameService: 構築したサービス。
    """
    from src.core.config import get_settings

    return GameService(repo=SongRepository(songs), templates=[], settings=get_settings())


def test_resolve_song_unique_match_returns_song() -> None:
    """部分一致が 1 件なら、その Song を返す。"""
    service = _service([_song("Dream"), _song("Pulses")])
    assert service.resolve_song("Pulses").title == "Pulses"


def test_resolve_song_no_match_raises_not_found() -> None:
    """部分一致が 0 件なら SongNotFound を送出し、query を保持する。"""
    service = _service([_song("Dream")])
    with pytest.raises(SongNotFound) as exc:
        service.resolve_song("zzz")
    assert exc.value.query == "zzz"


def test_resolve_song_multiple_matches_raises_ambiguous() -> None:
    """部分一致が複数なら AmbiguousSong を送出し、候補を保持する。"""
    service = _service([_song("Dream"), _song("Dreamy"), _song("Pulses")])
    with pytest.raises(AmbiguousSong) as exc:
        service.resolve_song("Dream")
    assert {s.title for s in exc.value.matches} == {"Dream", "Dreamy"}


from src.bot.game_service import format_topic_list
from src.game.models import PlayCondition, ProgressKind, Topic, TopicType


def _topic(panel_no: int, *, progress: int, required: int, completed: bool) -> Topic:
    """テスト用のお題を組み立てる。

    Args:
        panel_no: パネル番号。
        progress: 現在の進捗。
        required: 達成に必要な値。
        completed: 達成済みか。

    Returns:
        Topic: 構築したお題。
    """
    return Topic(
        panel_no=panel_no,
        topic_type=TopicType.TITLE_INCLUDE,
        play_condition=PlayCondition.PLAY,
        filter_value=("a",),
        required=required,
        progress_kind=ProgressKind.COUNT,
        description=f"説明{panel_no}",
        progress=progress,
        completed=completed,
    )


def test_format_topic_list_orders_by_panel_and_shows_progress() -> None:
    """パネル番号順に「パネルN: 説明 [x/y]」を並べ、達成行には達成表示を付ける。"""
    topics = [
        _topic(2, progress=3, required=3, completed=True),
        _topic(1, progress=1, required=2, completed=False),
    ]
    assert format_topic_list(topics) == (
        "パネル1: 説明1 [1/2]\n"
        "パネル2: 説明2 [3/3] 達成"
    )
