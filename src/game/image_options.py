from __future__ import annotations

import random

from src.game.models import ImageOptions

_ROTATE_ANGLES = (0, 90, 180, 270)


def resolve_image_options(
    *,
    rotate: bool,
    grayscale: bool,
    mosaic_px: int | None,
    rng: random.Random,
) -> ImageOptions:
    """セッション開始時の画像加工設定を確定する。

    回転角はここで一度だけ抽選し、以後セッション中固定する。

    Args:
        rotate: 回転を行うか。True なら 0/90/180/270 から 1 つ抽選する。
        grayscale: グレースケール化するか。
        mosaic_px: モザイクの縮小先 px。None ならモザイクなし。
        rng: 回転角抽選に使う乱数源(テストで注入可能にするため引数化)。

    Returns:
        ImageOptions: 解決済みの加工設定。
    """
    angle = rng.choice(_ROTATE_ANGLES) if rotate else None
    return ImageOptions(rotate=angle, grayscale=grayscale, mosaic_px=mosaic_px)
