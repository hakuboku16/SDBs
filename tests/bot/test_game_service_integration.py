import random
from datetime import datetime

from src.bot.game_service import GameService
from src.core.config import get_settings

_NOW = datetime(2026, 6, 10, 12, 0, 0)


def _service() -> GameService:
    """実アセットを読み込んだ、乱数固定の GameService を作る。

    Returns:
        GameService: assets 配下の実データを保持するサービス。
    """
    return GameService.from_settings(get_settings(), rng=random.Random(0))


def test_start_session_generates_topics_and_picks_hidden_song() -> None:
    """開始でお題が panel_count 個生成され、画像を持つ隠し曲が選ばれ、アクティブになる。"""
    service = _service()
    session = service.start_session(
        panel_count=4,
        rotate=False,
        grayscale=False,
        mosaic_px=None,
        now=_NOW,
    )
    assert session.panel_count == 4
    assert len(session.topics) == 4
    assert session.hidden_song.image_path is not None
    assert service.session is session
    assert {t.panel_no for t in session.topics} == {1, 2, 3, 4}


def test_start_session_sets_ends_at_from_settings_duration() -> None:
    """ends_at は started_at + 設定の継続時間(分)になる。"""
    service = _service()
    session = service.start_session(
        panel_count=4, rotate=False, grayscale=False, mosaic_px=None, now=_NOW
    )
    duration = get_settings().session_duration_minutes
    assert (session.ends_at - session.started_at).total_seconds() == duration * 60


from io import BytesIO

from PIL import Image


def test_render_current_board_returns_300px_png() -> None:
    """開始後の盤面描画は 300px 正方の PNG を返す。"""
    service = _service()
    service.start_session(
        panel_count=4, rotate=False, grayscale=False, mosaic_px=None, now=_NOW
    )
    out = Image.open(BytesIO(service.render_current_board()))
    assert out.format == "PNG"
    assert out.size == (300, 300)
