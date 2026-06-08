from io import BytesIO
from pathlib import Path

from PIL import Image

from src.game.board import _PANEL_FILL, process_image, render_board
from src.game.models import ImageOptions


def _opts(
    *, rotate: int | None = None, grayscale: bool = False, mosaic_px: int | None = None
) -> ImageOptions:
    return ImageOptions(rotate=rotate, grayscale=grayscale, mosaic_px=mosaic_px)


def _half_image() -> Image.Image:
    # 上半分=赤 / 下半分=青の非対称画像。回転・スライスの差を検出できる。
    img = Image.new("RGB", (300, 300), (255, 0, 0))
    img.paste((0, 0, 255), (0, 150, 300, 300))
    return img


def test_process_identity_keeps_pixels() -> None:
    out = process_image(_half_image(), _opts())
    assert out.getpixel((10, 10)) == (255, 0, 0)
    assert out.getpixel((10, 290)) == (0, 0, 255)


def test_process_grayscale_makes_channels_equal() -> None:
    r, g, b = process_image(_half_image(), _opts(grayscale=True)).getpixel((10, 10))
    assert r == g == b


def test_process_rotate_180_flips_top_and_bottom() -> None:
    out = process_image(_half_image(), _opts(rotate=180))
    assert out.getpixel((10, 10)) == (0, 0, 255)
    assert out.getpixel((10, 290)) == (255, 0, 0)


def test_process_mosaic_creates_uniform_blocks() -> None:
    # 横グラデーションをモザイク化すると 1 ブロック内が同色になる。
    grad = Image.new("RGB", (300, 300))
    for x in range(300):
        grad.paste((x // 2, 0, 0), (x, 0, x + 1, 300))
    out = process_image(grad, _opts(mosaic_px=30))
    block = 300 // 30  # 10px 角のブロック
    assert out.getpixel((0, 0)) == out.getpixel((block - 1, block - 1))


def _png_path(tmp_path: Path, img: Image.Image) -> Path:
    path = tmp_path / "hidden.png"
    img.save(path, format="PNG")
    return path


def test_render_returns_300px_png(tmp_path: Path) -> None:
    path = _png_path(tmp_path, _half_image())
    data = render_board(path, grid_size=3, revealed_panels=set(), options=_opts())
    out = Image.open(BytesIO(data))
    assert out.format == "PNG"
    assert out.size == (300, 300)


def test_render_covered_tile_differs_from_revealed(tmp_path: Path) -> None:
    path = _png_path(tmp_path, _half_image())
    covered = Image.open(
        BytesIO(render_board(path, grid_size=2, revealed_panels=set(), options=_opts()))
    ).convert("RGB")
    revealed = Image.open(
        BytesIO(render_board(path, grid_size=2, revealed_panels={1}, options=_opts()))
    ).convert("RGB")
    # パネル1=左上タイル(0,0)-(150,150)の中心 (40,40)。
    assert covered.getpixel((40, 40)) != revealed.getpixel((40, 40))
    assert revealed.getpixel((40, 40)) == (255, 0, 0)


def test_render_reveals_correct_panel_by_number(tmp_path: Path) -> None:
    # 2x2。パネル3=左下、パネル4=右下。下半分は青。
    path = _png_path(tmp_path, _half_image())
    board = Image.open(
        BytesIO(render_board(path, grid_size=2, revealed_panels={3}, options=_opts()))
    ).convert("RGB")
    assert board.getpixel((40, 220)) == (0, 0, 255)   # パネル3=開示(画像の青)
    assert board.getpixel((220, 220)) == _PANEL_FILL   # パネル4=被覆(パネル色)
