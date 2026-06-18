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
    """完全一致が無く部分一致が複数なら AmbiguousSong を送出し、候補を保持する。"""
    service = _service([_song("Dream"), _song("Dreamy"), _song("Pulses")])
    with pytest.raises(AmbiguousSong) as exc:
        service.resolve_song("Drea")
    assert {s.title for s in exc.value.matches} == {"Dream", "Dreamy"}


def test_resolve_song_exact_title_match_wins_over_substring() -> None:
    """query が曲名と完全一致するなら、部分文字列で複数ヒットしてもその曲を返す。"""
    service = _service([_song("Dream"), _song("Dreamy")])
    assert service.resolve_song("Dream").title == "Dream"


def test_resolve_song_exact_match_is_normalized_and_case_insensitive() -> None:
    """完全一致判定は正規化 + 大文字小文字無視で行う。"""
    service = _service([_song("Dream"), _song("Dreamy")])
    assert service.resolve_song("dream").title == "Dream"


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


from datetime import datetime, timedelta

from src.bot.game_service import timer_delays
from src.game.models import GameSession, ImageOptions


def _session_for_timer(now: datetime) -> GameSession:
    """タイマー計算用に ends_at だけ意味を持つ最小セッションを作る。

    Args:
        now: started_at。ends_at は now+30 分にする。

    Returns:
        GameSession: 計算対象のセッション。
    """
    return GameSession(
        panel_count=4,
        hidden_song=_song("Dream", image=True),
        image_options=ImageOptions(rotate=None, grayscale=False, mosaic_px=None),
        topics=[],
        started_at=now,
        ends_at=now + timedelta(minutes=30),
    )


def test_timer_delays_returns_warning_and_end_seconds() -> None:
    """予告は ends_at の warning 分前、終了は ends_at までの秒数を返す。"""
    now = datetime(2026, 6, 10, 12, 0, 0)
    warn, end = timer_delays(_session_for_timer(now), now=now, warning_minutes=10)
    assert (warn, end) == (1200.0, 1800.0)


def test_cancel_timer_is_noop_without_task() -> None:
    """タイマータスク未設定でも cancel_timer は例外を出さない。"""
    service = _service([_song("Dream")])
    service.cancel_timer()  # 何も起きない
    assert service.timer_task is None


from src.bot.game_service import GENERIC_ERROR_MESSAGE


def test_generic_error_message_is_user_facing_japanese() -> None:
    """汎用エラー文言は内部情報を含まない利用者向けの定型文である。"""
    assert "エラー" in GENERIC_ERROR_MESSAGE
    assert "Traceback" not in GENERIC_ERROR_MESSAGE


from src.bot.game_service import format_archive_caption


def _session_with_answerers(answerers: list[int]) -> GameSession:
    """正解者リストだけ意味を持つ最小セッションを作る。

    Args:
        answerers: correct_answerers に入れるユーザー ID リスト(正解順)。

    Returns:
        GameSession: 構築したセッション。
    """
    now = datetime(2026, 6, 10, 12, 0, 0)
    return GameSession(
        panel_count=4,
        hidden_song=_song("Dream", image=True),
        image_options=ImageOptions(rotate=None, grayscale=False, mosaic_px=None),
        topics=[],
        started_at=now,
        ends_at=now + timedelta(minutes=30),
        correct_answerers=answerers,
    )


def test_archive_caption_spoilers_title_with_book_and_lists_answerers_in_order() -> None:
    """楽曲名+パック名(book)をネタバレ記法で隠し、正解者を正解順で列挙する。"""
    caption = format_archive_caption(_session_with_answerers([111, 222]))
    assert caption == "楽曲名: ||Dream (Vol.1A)||\n正解者:\n<@111>\n<@222>"


def test_archive_caption_shows_none_when_no_answerers() -> None:
    """正解者がいなければ「正解者なし」と表示する。"""
    caption = format_archive_caption(_session_with_answerers([]))
    assert caption == "楽曲名: ||Dream (Vol.1A)||\n正解者:\n正解者なし"


from src.bot.game_service import (
    format_panel_list,
    format_progress_text,
    format_session_options,
)


def test_format_panel_list_marks_completed_and_orders_by_panel() -> None:
    """パネル番号順に達成は✅、未達成は⬜を付け、説明を次行に並べる。"""
    topics = [
        _topic(2, progress=3, required=3, completed=True),
        _topic(1, progress=1, required=2, completed=False),
    ]
    assert format_panel_list(topics) == (
        "⬜ **パネル 1 (1/2)**\n説明1\n✅ **パネル 2 (3/3)**\n説明2"
    )


def test_format_session_options_lists_mosaic_with_pixels() -> None:
    """オプションを箇条書きにし、モザイクは実効解像度 px を併記する。"""
    session = _session_for_timer(datetime(2026, 6, 10, 12, 0, 0))
    session.panel_count = 9
    session.image_options = ImageOptions(rotate=90, grayscale=False, mosaic_px=None)
    assert format_session_options(session) == (
        "・パネル数:9\n・回転:有効\n・グレースケール:無効\n・モザイク:なし (300px)"
    )


def test_format_progress_text_shows_remaining_minutes_and_topics() -> None:
    """残り時間(分・切り捨て)とお題リストを併記する。"""
    session = _session_for_timer(datetime(2026, 6, 10, 12, 0, 0))
    session.topics = [_topic(1, progress=1, required=2, completed=False)]
    text = format_progress_text(session, timedelta(minutes=12, seconds=30))
    assert text == "残り時間: 約12分\n\nパネル1: 説明1 [1/2]"


def test_format_progress_text_clamps_negative_remaining_to_zero() -> None:
    """残り時間が負なら 0 分として表示する。"""
    session = _session_for_timer(datetime(2026, 6, 10, 12, 0, 0))
    session.topics = []
    text = format_progress_text(session, timedelta(seconds=-5))
    assert text.startswith("残り時間: 約0分")


def test_suggest_song_titles_empty_query_returns_first_n_sorted() -> None:
    """空入力なら全曲名を昇順ソートし先頭 limit 件を返す。"""
    service = _service([_song("Cytus"), _song("Anima"), _song("Bond")])
    assert service.suggest_song_titles("", limit=2) == ["Anima", "Bond"]


def test_suggest_song_titles_filters_by_partial_match_sorted() -> None:
    """非空入力は部分一致で絞り込み、曲名昇順で返す。"""
    service = _service([_song("Dreamy"), _song("Dream"), _song("Pulses")])
    assert service.suggest_song_titles("dre") == ["Dream", "Dreamy"]


def test_suggest_song_titles_caps_at_limit() -> None:
    """一致が limit を超えても limit 件で打ち切る。"""
    service = _service([_song(f"Song{i:02d}") for i in range(30)])
    assert len(service.suggest_song_titles("Song", limit=25)) == 25
