from __future__ import annotations

from PIL import Image

from src.game.models import ImageOptions

CANVAS_SIZE = 300

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
