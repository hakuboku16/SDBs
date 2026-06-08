import random

from src.game.image_options import resolve_image_options


def test_resolve_no_rotate_yields_none() -> None:
    opts = resolve_image_options(
        rotate=False, grayscale=True, mosaic_px=90, rng=random.Random(0)
    )
    assert opts.rotate is None
    assert opts.grayscale is True
    assert opts.mosaic_px == 90


def test_resolve_rotate_picks_from_allowed_angles() -> None:
    opts = resolve_image_options(
        rotate=True, grayscale=False, mosaic_px=None, rng=random.Random(0)
    )
    assert opts.rotate in (0, 90, 180, 270)


def test_resolve_rotate_is_deterministic_for_seed() -> None:
    a = resolve_image_options(
        rotate=True, grayscale=False, mosaic_px=None, rng=random.Random(123)
    )
    b = resolve_image_options(
        rotate=True, grayscale=False, mosaic_px=None, rng=random.Random(123)
    )
    assert a.rotate == b.rotate
