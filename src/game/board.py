from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from src.game.models import ImageOptions

CANVAS_SIZE = 300
_PANEL_FILL = (40, 40, 40)
_NUMBER_FILL = (255, 255, 255)

_ROTATE_OPS = {
    90: Image.Transpose.ROTATE_90,
    180: Image.Transpose.ROTATE_180,
    270: Image.Transpose.ROTATE_270,
}


def process_image(image: Image.Image, options: ImageOptions) -> Image.Image:
    """基準画像へ加工を回転→グレースケール→モザイクの順で適用する。

    Args:
        image: 300px 正方の RGB 画像。
        options: 適用する加工設定(解決済み)。

    Returns:
        Image.Image: 加工後の 300px 正方 RGB 画像。
    """
    result = image
    # 回転は 90 度単位のため transpose で補間なしに行い、テストの厳密一致を保つ。
    if options.rotate:
        result = result.transpose(_ROTATE_OPS[options.rotate])
    if options.grayscale:
        result = result.convert("L").convert("RGB")
    if options.mosaic_px:
        small = result.resize(
            (options.mosaic_px, options.mosaic_px), Image.Resampling.BILINEAR
        )
        result = small.resize((CANVAS_SIZE, CANVAS_SIZE), Image.Resampling.NEAREST)
    return result


def render_board(
    image_path: Path,
    *,
    grid_size: int,
    revealed_panels: set[int],
    options: ImageOptions,
) -> bytes:
    """隠し曲画像から現在の盤面を合成し PNG バイト列を返す。

    未開示パネルは番号入りの不透明パネルで被覆し、開示済みパネルは
    加工後画像のスライスを表示する。

    Args:
        image_path: 隠し曲のジャケット画像パス。
        grid_size: 盤面の一辺のパネル数(2/3/4/5)。
        revealed_panels: 開示済みパネル番号(1..grid_size**2)の集合。
        options: 画像加工設定(解決済み)。

    Returns:
        bytes: PNG エンコードした盤面画像。
    """
    with Image.open(image_path) as raw:
        base = raw.convert("RGB").resize((CANVAS_SIZE, CANVAS_SIZE))
    processed = process_image(base, options)

    tile = CANVAS_SIZE // grid_size
    board = Image.new("RGB", (CANVAS_SIZE, CANVAS_SIZE))
    draw = ImageDraw.Draw(board)
    font = ImageFont.load_default()

    for row in range(grid_size):
        for col in range(grid_size):
            panel_no = row * grid_size + col + 1
            box = (col * tile, row * tile, (col + 1) * tile, (row + 1) * tile)
            if panel_no in revealed_panels:
                board.paste(processed.crop(box), (box[0], box[1]))
            else:
                _draw_panel(draw, box, panel_no, font)

    buffer = BytesIO()
    board.save(buffer, format="PNG")
    return buffer.getvalue()


def _draw_panel(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    number: int,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> None:
    """未開示タイルへ不透明パネルと中央寄せの番号を描く。

    Args:
        draw: 描画対象の ImageDraw。
        box: タイルの矩形 (left, top, right, bottom)。
        number: 表示するパネル番号。
        font: 番号描画に使うフォント。
    """
    left, top, right, bottom = box
    draw.rectangle(box, fill=_PANEL_FILL)
    text = str(number)
    text_box = draw.textbbox((0, 0), text, font=font)
    text_w = text_box[2] - text_box[0]
    text_h = text_box[3] - text_box[1]
    cx = left + (right - left - text_w) / 2
    cy = top + (bottom - top - text_h) / 2
    draw.text((cx, cy), text, fill=_NUMBER_FILL, font=font)
