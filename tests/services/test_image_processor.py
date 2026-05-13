"""
image_processor.py のユニットテスト

ステップ 3.1: 画像読み込み・回転・グレースケール・モザイクの単体検証
ステップ 3.2 / 3.3 のテストは実装時に追記する。
"""

import json
import random
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from src.services.image_processor import ImageProcessor
from src.services.song_repository import SongRepository


# ==================================================
# fixtures
# ==================================================
@pytest.fixture
def sample_image_path(tmp_path: Path) -> Path:
    """
    検証用にカラフルな 4 色 (300x300) の正方形画像を生成し、そのパスを返す

    ピクセル位置で色が判定できるよう、4 象限を異なる色で塗り分ける:
        左上 (0,0) = 赤、右上 (299,0) = 緑、左下 (0,299) = 青、右下 (299,299) = 黄
    """
    image = Image.new("RGB", (300, 300))
    pixels = image.load()
    for y in range(300):
        for x in range(300):
            if x < 150 and y < 150:
                pixels[x, y] = (255, 0, 0)
            elif x >= 150 and y < 150:
                pixels[x, y] = (0, 255, 0)
            elif x < 150 and y >= 150:
                pixels[x, y] = (0, 0, 255)
            else:
                pixels[x, y] = (255, 255, 0)
    path = tmp_path / "Sample Song.png"
    image.save(path, format="PNG")
    return path


@pytest.fixture
def fake_repo(tmp_path: Path, sample_image_path: Path) -> SongRepository:
    """
    sample_image_path に対応する 1 曲だけを持つ最小構成の SongRepository
    """
    data = {
        "ShelfA": {
            "BookA": {
                sample_image_path.stem: {
                    "VERSION": "1.0",
                    "LEVEL": {"Easy": 1, "Normal": 4, "Hard": 8},
                    "NOTES": {"Easy": 100, "Normal": 200, "Hard": 300},
                    "TIME": 120,
                    "COMPOSER": ["Composer A"],
                },
            },
        },
    }
    songs_json = tmp_path / "songs.json"
    songs_json.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    return SongRepository(songs_json=songs_json, images_dir=tmp_path)


@pytest.fixture
def processor(fake_repo: SongRepository) -> ImageProcessor:
    """
    乱数を固定した ImageProcessor (回転角の決定論性確保)
    """
    return ImageProcessor(song_repository=fake_repo, rng=random.Random(42))


# ==================================================
# 画像読み込み
# ==================================================
class TestLoadImage:
    """
    `_load_image` の挙動を検証
    """

    def test_load_returns_rgb_image_with_expected_size(
        self, processor: ImageProcessor
    ):
        """
        読み込んだ画像はサイズ・モードを保持する
        """
        image = processor._load_image("Sample Song")
        assert image.size == (300, 300)
        assert image.mode == "RGB"

    def test_load_missing_image_raises(self, processor: ImageProcessor):
        """
        存在しない楽曲名は FileNotFoundError
        """
        with pytest.raises(FileNotFoundError, match="Nonexistent Song"):
            processor._load_image("Nonexistent Song")

    def test_load_converts_non_rgb_to_rgb(
        self, processor: ImageProcessor, fake_repo: SongRepository, tmp_path: Path
    ):
        """
        元画像が RGBA など他モードでも RGB に変換されて返る
        """
        # fake_repo の images_dir は tmp_path 直下なので、同じ名前で RGBA を上書き
        rgba = Image.new("RGBA", (300, 300), (10, 20, 30, 200))
        rgba.save(tmp_path / "Sample Song.png", format="PNG")

        image = processor._load_image("Sample Song")
        assert image.mode == "RGB"


# ==================================================
# 回転
# ==================================================
class TestApplyRotation:
    """
    `_apply_rotation` および `pick_rotation_angle` の挙動を検証
    """

    def test_rotation_keeps_size(self, processor: ImageProcessor):
        """
        指定角度で回転しても画像サイズは保たれる (expand=False)
        """
        image = processor._load_image("Sample Song")
        rotated = processor._apply_rotation(image, angle=90)
        assert rotated.size == image.size

    def test_rotation_actually_changes_pixels(self, processor: ImageProcessor):
        """
        回転後は左上ピクセルの色が元画像 (赤) と異なる
        """
        image = processor._load_image("Sample Song")
        original_top_left = image.getpixel((0, 0))
        rotated = processor._apply_rotation(image, angle=90)
        assert rotated.getpixel((0, 0)) != original_top_left

    def test_pick_rotation_angle_returns_only_0_90_180_270(
        self, fake_repo: SongRepository
    ):
        """
        `pick_rotation_angle` の戻り値は 0/90/180/270 のいずれか
        100 回試行して 4 角度のいずれかであることを確認する。
        """
        proc = ImageProcessor(song_repository=fake_repo)
        allowed = {0, 90, 180, 270}
        for _ in range(100):
            assert proc.pick_rotation_angle() in allowed

    def test_pick_rotation_angle_uses_injected_rng(
        self, fake_repo: SongRepository
    ):
        """
        rng を注入した場合、`pick_rotation_angle` は注入した seed に従って決定論的に動く。
        Why: セッション開始時に決めた角度がテストでも再現できることを保証する。
        """
        proc1 = ImageProcessor(song_repository=fake_repo, rng=random.Random(42))
        proc2 = ImageProcessor(song_repository=fake_repo, rng=random.Random(42))
        # 同 seed なら最初の結果は一致
        assert proc1.pick_rotation_angle() == proc2.pick_rotation_angle()


# ==================================================
# グレースケール
# ==================================================
class TestApplyGrayscale:
    """
    `_apply_grayscale` の挙動を検証
    """

    def test_grayscale_returns_rgb_mode(self, processor: ImageProcessor):
        """
        グレースケール処理後も RGB モードで返る (パネル合成側との整合のため)
        """
        image = processor._load_image("Sample Song")
        gray = processor._apply_grayscale(image)
        assert gray.mode == "RGB"
        assert gray.size == image.size

    def test_grayscale_pixel_components_are_equal(self, processor: ImageProcessor):
        """
        グレースケール RGB は各ピクセルで R == G == B
        """
        image = processor._load_image("Sample Song")
        gray = processor._apply_grayscale(image)
        # 4 象限の中央ピクセルで検証
        for x, y in [(75, 75), (225, 75), (75, 225), (225, 225)]:
            r, g, b = gray.getpixel((x, y))
            assert r == g == b


# ==================================================
# モザイク
# ==================================================
class TestApplyMosaic:
    """
    `_apply_mosaic` の挙動を検証
    """

    def test_mosaic_keeps_size(self, processor: ImageProcessor):
        """
        モザイク適用後も元画像サイズに復元される
        """
        image = processor._load_image("Sample Song")
        mosaiced = processor._apply_mosaic(image, block=27)
        assert mosaiced.size == image.size

    def test_mosaic_block_equal_to_size_is_noop_like(
        self, processor: ImageProcessor
    ):
        """
        block が元画像サイズと同じ (300) 場合、ピクセル数は保たれ実質的に no-op
        """
        image = processor._load_image("Sample Song")
        result = processor._apply_mosaic(image, block=300)
        assert result.size == image.size
        # 中央ピクセルが元と一致 (downscale→upscale が同サイズなら NEAREST で復元される)
        assert result.getpixel((75, 75)) == image.getpixel((75, 75))

    def test_mosaic_strongest_block_collapses_to_single_color(
        self, processor: ImageProcessor
    ):
        """
        block=1 では全画素が 1 色に潰れる (極限ケースとしてのモザイク強度確認)
        """
        image = processor._load_image("Sample Song")
        result = processor._apply_mosaic(image, block=1)
        sampled = {result.getpixel((x, y)) for x in range(0, 300, 50) for y in range(0, 300, 50)}
        assert len(sampled) == 1

    def test_mosaic_block_27_reduces_unique_colors(self, processor: ImageProcessor):
        """
        実運用の最強モザイク (block=27) では 300x300 を 27x27 まで縮めるため、
        4 象限境界に複数の中間色が現れ、サンプリングするとユニーク色数が増える。
        ここでは「中央付近のピクセルは赤一色ではない (境界の影響を受ける)」ことを検証する。
        """
        image = processor._load_image("Sample Song")
        result = processor._apply_mosaic(image, block=27)
        # 左上象限 (赤) の中央 (75, 75) が赤のままでも、
        # 4 象限境界 (148〜152) では別象限の色が混入する
        boundary_colors = {result.getpixel((x, 150)) for x in range(140, 161, 2)}
        # 1 象限の単色のみではなく、複数色が境界に現れる
        assert len(boundary_colors) >= 2

    def test_mosaic_invalid_block_raises(self, processor: ImageProcessor):
        """
        block が 0 以下なら ValueError
        """
        image = processor._load_image("Sample Song")
        with pytest.raises(ValueError, match="1 以上"):
            processor._apply_mosaic(image, block=0)
        with pytest.raises(ValueError, match="1 以上"):
            processor._apply_mosaic(image, block=-5)


# ==================================================
# パネルグリッド合成
# ==================================================
class TestOverlayPanels:
    """
    `_overlay_panels` のグリッド分割・cleared 透過・番号描画の挙動を検証
    """

    PANEL_FILL = ImageProcessor._PANEL_FILL_COLOR

    def test_overlay_returns_same_size(self, processor: ImageProcessor):
        """
        合成結果は元画像と同じサイズ
        """
        image = processor._load_image("Sample Song")
        result = processor._overlay_panels(image, panel_count=4, cleared_indices=set())
        assert result.size == image.size

    def test_overlay_does_not_modify_input(self, processor: ImageProcessor):
        """
        合成は入力画像を破壊しない (元画像は変更されない)
        """
        image = processor._load_image("Sample Song")
        original_pixel = image.getpixel((75, 75))
        processor._overlay_panels(image, panel_count=4, cleared_indices=set())
        assert image.getpixel((75, 75)) == original_pixel

    def test_all_cleared_keeps_original_pixels(self, processor: ImageProcessor):
        """
        全てのセルが cleared なら元画像と全画素が等しい
        """
        image = processor._load_image("Sample Song")
        result = processor._overlay_panels(
            image, panel_count=4, cleared_indices={0, 1, 2, 3}
        )
        # 4 象限の中央ピクセルは元画像と一致
        for x, y in [(75, 75), (225, 75), (75, 225), (225, 225)]:
            assert result.getpixel((x, y)) == image.getpixel((x, y))

    def test_all_uncleared_overlays_panel_color_at_cell_centers(
        self, processor: ImageProcessor
    ):
        """
        全セル未クリアなら、各セルの中央近傍はパネル色 (塗りつぶし) で覆われる

        中央近傍 (番号文字の影響を避けるため、セル左上寄りのオフセット位置) を確認する。
        """
        image = processor._load_image("Sample Song")
        result = processor._overlay_panels(
            image, panel_count=4, cleared_indices=set()
        )
        # 4 セル (2x2)。各セルは 150x150。番号は中央なので
        # 左上から 30px の位置 (パネル塗り部分) を確認
        for cx, cy in [(30, 30), (180, 30), (30, 180), (180, 180)]:
            assert result.getpixel((cx, cy)) == self.PANEL_FILL

    def test_partial_cleared_only_uncovers_specified_cells(
        self, processor: ImageProcessor
    ):
        """
        cleared_indices に指定したセルのみ元画像が露出し、他はパネル色で覆われる
        """
        image = processor._load_image("Sample Song")
        # 4 セルのうち 0 (左上, 赤) と 3 (右下, 黄) のみクリア
        result = processor._overlay_panels(
            image, panel_count=4, cleared_indices={0, 3}
        )

        # cleared セル中央近傍は元画像 (赤 / 黄) のまま
        assert result.getpixel((30, 30)) == (255, 0, 0)
        assert result.getpixel((250, 250)) == (255, 255, 0)

        # 未 cleared セル (右上, 左下) はパネル色
        assert result.getpixel((180, 30)) == self.PANEL_FILL
        assert result.getpixel((30, 180)) == self.PANEL_FILL

    @pytest.mark.parametrize("panel_count", [4, 9, 16, 25])
    def test_supports_all_allowed_panel_counts(
        self, processor: ImageProcessor, panel_count: int
    ):
        """
        要件で許容される全パネル数 (4 / 9 / 16 / 25) で例外なく合成できる
        """
        image = processor._load_image("Sample Song")
        result = processor._overlay_panels(
            image, panel_count=panel_count, cleared_indices=set()
        )
        assert result.size == image.size

    def test_overlay_invalid_panel_count_raises(self, processor: ImageProcessor):
        """
        平方数でない panel_count は ValueError
        """
        image = processor._load_image("Sample Song")
        with pytest.raises(ValueError, match="平方数"):
            processor._overlay_panels(image, panel_count=5, cleared_indices=set())

    def test_overlay_out_of_range_cleared_index_raises(
        self, processor: ImageProcessor
    ):
        """
        cleared_indices が範囲外なら ValueError
        """
        image = processor._load_image("Sample Song")
        with pytest.raises(ValueError, match="範囲内"):
            processor._overlay_panels(image, panel_count=4, cleared_indices={4})
        with pytest.raises(ValueError, match="範囲内"):
            processor._overlay_panels(image, panel_count=4, cleared_indices={-1})


# ==================================================
# compose 統合 (エンドツーエンド)
# ==================================================
class TestCompose:
    """
    `compose` の統合的な振る舞いを検証

    - 出力 PNG のフォーマット / サイズの整合性
    - 各引数 (rotate / grayscale / mosaic / cleared_indices) が compose 全体に正しく伝播するか
    - 入力バリデーション
    """

    PANEL_FILL = ImageProcessor._PANEL_FILL_COLOR

    def test_compose_returns_valid_png_with_original_size(
        self, processor: ImageProcessor
    ):
        """
        compose の戻り値は PNG として読み込め、元画像サイズが保たれる
        """
        buffer = processor.compose(
            song_name="Sample Song",
            panel_count=4,
            cleared_indices=set(),
            rotation_angle=None,
            grayscale=False,
            mosaic_block=300,
        )
        assert isinstance(buffer, BytesIO)
        # シーク位置が先頭であることを確認
        assert buffer.tell() == 0

        result = Image.open(buffer)
        assert result.format == "PNG"
        assert result.size == (300, 300)

    def test_compose_no_effects_with_all_cleared_matches_original(
        self, processor: ImageProcessor
    ):
        """
        全エフェクト無効 + 全 cleared なら元画像の各象限色が保たれる
        """
        buffer = processor.compose(
            song_name="Sample Song",
            panel_count=4,
            cleared_indices={0, 1, 2, 3},
            rotation_angle=None,
            grayscale=False,
            mosaic_block=300,
        )
        result = Image.open(buffer).convert("RGB")
        # 4 象限の中央
        assert result.getpixel((75, 75)) == (255, 0, 0)
        assert result.getpixel((225, 75)) == (0, 255, 0)
        assert result.getpixel((75, 225)) == (0, 0, 255)
        assert result.getpixel((225, 225)) == (255, 255, 0)

    def test_compose_no_cleared_covers_with_panel_color(
        self, processor: ImageProcessor
    ):
        """
        cleared_indices が空ならパネル色で全面を覆う (中央は番号文字なので外す)
        """
        buffer = processor.compose(
            song_name="Sample Song",
            panel_count=4,
            cleared_indices=set(),
            rotation_angle=None,
            grayscale=False,
            mosaic_block=300,
        )
        result = Image.open(buffer).convert("RGB")
        # 各セル (150x150) の左上寄りはパネル塗り (番号文字に当たらない位置)
        for cx, cy in [(30, 30), (180, 30), (30, 180), (180, 180)]:
            assert result.getpixel((cx, cy)) == self.PANEL_FILL

    def test_compose_partial_cleared_visible_only_on_cleared(
        self, processor: ImageProcessor
    ):
        """
        cleared セルのみ元画像が露出し、他はパネル色で覆われる (合成全体の整合性)
        """
        buffer = processor.compose(
            song_name="Sample Song",
            panel_count=4,
            cleared_indices={0, 3},
            rotation_angle=None,
            grayscale=False,
            mosaic_block=300,
        )
        result = Image.open(buffer).convert("RGB")

        # cleared (左上 / 右下) は元の赤 / 黄
        assert result.getpixel((30, 30)) == (255, 0, 0)
        assert result.getpixel((250, 250)) == (255, 255, 0)
        # 未 cleared (右上 / 左下) はパネル色
        assert result.getpixel((180, 30)) == self.PANEL_FILL
        assert result.getpixel((30, 180)) == self.PANEL_FILL

    def test_compose_grayscale_makes_cleared_pixels_gray(
        self, processor: ImageProcessor
    ):
        """
        grayscale=True なら、cleared セル (元画像が露出する位置) のピクセルは R==G==B
        """
        buffer = processor.compose(
            song_name="Sample Song",
            panel_count=4,
            cleared_indices={0, 1, 2, 3},
            rotation_angle=None,
            grayscale=True,
            mosaic_block=300,
        )
        result = Image.open(buffer).convert("RGB")
        # 全セルが cleared なので画像全体が見える。グレースケール後は R==G==B
        for x, y in [(75, 75), (225, 75), (75, 225), (225, 225)]:
            pixel = result.getpixel((x, y))
            assert isinstance(pixel, tuple) and len(pixel) == 3
            r, g, b = pixel
            assert r == g == b

    def test_compose_mosaic_strongest_makes_cleared_uniform(
        self, processor: ImageProcessor
    ):
        """
        mosaic_block=1 なら全画素が単一色に潰れる。cleared セル中央もその単一色を返す
        """
        buffer = processor.compose(
            song_name="Sample Song",
            panel_count=4,
            cleared_indices={0, 1, 2, 3},
            rotation_angle=None,
            grayscale=False,
            mosaic_block=1,
        )
        result = Image.open(buffer).convert("RGB")
        sampled = {result.getpixel((x, y)) for x in range(0, 300, 50) for y in range(0, 300, 50)}
        assert len(sampled) == 1

    def test_compose_rotate_changes_quadrant_colors(
        self, processor: ImageProcessor
    ):
        """
        rotation_angle 指定で 4 象限の色配置が変わる (cleared 全セルで全画素を露出させて確認)
        """
        original_buffer = processor.compose(
            song_name="Sample Song",
            panel_count=4,
            cleared_indices={0, 1, 2, 3},
            rotation_angle=None,
            grayscale=False,
            mosaic_block=300,
        )
        rotated_buffer = processor.compose(
            song_name="Sample Song",
            panel_count=4,
            cleared_indices={0, 1, 2, 3},
            rotation_angle=90,
            grayscale=False,
            mosaic_block=300,
        )
        original = Image.open(original_buffer).convert("RGB")
        rotated = Image.open(rotated_buffer).convert("RGB")
        # 左上の色が回転前 (赤) と異なる
        assert rotated.getpixel((75, 75)) != original.getpixel((75, 75))

    @pytest.mark.parametrize("panel_count", [4, 9, 16, 25])
    def test_compose_supports_all_allowed_panel_counts(
        self, processor: ImageProcessor, panel_count: int
    ):
        """
        要件で許容される全パネル数で compose が成功する
        """
        buffer = processor.compose(
            song_name="Sample Song",
            panel_count=panel_count,
            cleared_indices=set(),
            rotation_angle=None,
            grayscale=False,
            mosaic_block=300,
        )
        result = Image.open(buffer)
        assert result.size == (300, 300)

    # --- バリデーション ---
    def test_compose_invalid_mosaic_block_raises(self, processor: ImageProcessor):
        """
        mosaic_block が 0 以下なら ValueError
        """
        with pytest.raises(ValueError, match="mosaic_block"):
            processor.compose(
                song_name="Sample Song",
                panel_count=4,
                cleared_indices=set(),
                rotation_angle=None,
                grayscale=False,
                mosaic_block=0,
            )

    def test_compose_invalid_panel_count_raises(self, processor: ImageProcessor):
        """
        平方数でない panel_count は ValueError (内部で _overlay_panels が検出)
        """
        with pytest.raises(ValueError, match="平方数"):
            processor.compose(
                song_name="Sample Song",
                panel_count=5,
                cleared_indices=set(),
                rotation_angle=None,
                grayscale=False,
                mosaic_block=300,
            )

    def test_compose_out_of_range_cleared_index_raises(
        self, processor: ImageProcessor
    ):
        """
        cleared_indices が範囲外なら ValueError
        """
        with pytest.raises(ValueError, match="範囲内"):
            processor.compose(
                song_name="Sample Song",
                panel_count=4,
                cleared_indices={4},
                rotation_angle=None,
                grayscale=False,
                mosaic_block=300,
            )

    def test_compose_unknown_song_raises(self, processor: ImageProcessor):
        """
        楽曲画像が存在しない場合は FileNotFoundError
        """
        with pytest.raises(FileNotFoundError):
            processor.compose(
                song_name="Nonexistent Song",
                panel_count=4,
                cleared_indices=set(),
                rotation_angle=None,
                grayscale=False,
                mosaic_block=300,
            )
