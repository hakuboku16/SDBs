"""
楽曲ジャケット画像のエフェクト適用とパネル合成を行うモジュール

`ImageProcessor` は SongRepository を介して楽曲名から元画像を解決し、
回転 / グレースケール / モザイクの効果を適用したうえで、
N x N のパネルグリッドで覆った画像を合成します (ステップ 3.2 以降で実装)。

本モジュールはステップ 3.1 で導入された単一画像エフェクト機能を含みます。
"""

import math
import random
from io import BytesIO
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont
from PIL.ImageFont import FreeTypeFont, ImageFont as BitmapFont

from src.services.song_repository import SongRepository

# Pillow のフォントは新旧 2 系統 (ビットマップ / TrueType) があるため Union で扱う
_AnyFont = FreeTypeFont | BitmapFont


# ==================================================
# 画像処理クラス
# ==================================================
class ImageProcessor:
    """
    楽曲ジャケット画像にエフェクトを適用しパネル化するプロセッサ

    全ての楽曲ジャケットは 300x300 RGB を想定していますが、
    異なるサイズが入力されてもそのまま (orig_size を保ったまま) 処理します。
    """

    # 回転に用いる角度 (度)。`Image.rotate` は反時計回り
    _ROTATE_CHOICES: tuple[int, ...] = (90, 180, 270)

    # パネル (未クリア時の覆い) の塗り色 (RGB) と番号文字の色 (RGB)
    _PANEL_FILL_COLOR: tuple[int, int, int] = (40, 40, 40)
    _PANEL_BORDER_COLOR: tuple[int, int, int] = (200, 200, 200)
    _PANEL_BORDER_WIDTH: int = 2
    _PANEL_TEXT_COLOR: tuple[int, int, int] = (255, 255, 255)

    def __init__(
        self,
        song_repository: SongRepository,
        rng: Optional[random.Random] = None,
    ) -> None:
        """
        画像プロセッサを初期化する

        Args:
            song_repository: 楽曲名→画像パス解決に用いる SongRepository
            rng: ランダム回転角の選択に使う乱数生成器。テスト時に固定したい場合に注入する。
                None の場合はモジュールスコープの `random` を利用する。
        """
        self._song_repository: SongRepository = song_repository
        self._rng: random.Random = rng if rng is not None else random.Random()

    # --------------------------------------------------
    # 画像読み込み
    # --------------------------------------------------
    def _load_image(self, song_name: str) -> Image.Image:
        """
        楽曲名から元画像を読み込む

        Args:
            song_name: 楽曲名 (`Song.name` と一致)

        Returns:
            読み込んだ画像 (RGB モードに正規化)

        Raises:
            FileNotFoundError: 楽曲に対応する画像ファイルが存在しない場合
        """
        path: Path = self._song_repository.get_image_path(song_name)
        if not path.is_file():
            raise FileNotFoundError(
                f"楽曲 '{song_name}' のジャケット画像が見つかりません: {path}"
            )

        image: Image.Image = Image.open(path)
        # 画像のモードが RGB 以外でも以降の処理を一貫させるため明示的に変換
        if image.mode != "RGB":
            image = image.convert("RGB")
        return image

    # --------------------------------------------------
    # 単一画像エフェクト
    # --------------------------------------------------
    def pick_rotation_angle(self) -> int:
        """
        回転に用いる角度 (90 / 180 / 270 度) をランダムに 1 つ選んで返す

        Why: 1 セッションを通じて回転角度を固定するため、角度決定 (`pick_rotation_angle`)
        と適用 (`compose` への `rotation_angle` 引数) を分離している。呼び出し側 (cog)
        が決定済みの角度を `Session` に保持し、その後の `compose` 呼び出しで同じ角度を
        繰り返し渡せる構造にする。

        Returns:
            `_ROTATE_CHOICES` のいずれかの角度 (度)
        """
        return self._rng.choice(self._ROTATE_CHOICES)

    def _apply_rotation(self, image: Image.Image, angle: int) -> Image.Image:
        """
        指定された角度で画像を回転する

        Args:
            image: 元画像
            angle: 回転角度 (度)。`_ROTATE_CHOICES` 想定だが他角度でも動作する

        Returns:
            回転後の新しい画像 (元画像は変更しない)
        """
        # expand=True にすると回転後にキャンバスが拡張されるが、
        # 90/180/270 度では正方形のまま、サイズが保たれる前提で expand=False を選択
        return image.rotate(angle, expand=False)

    def _apply_grayscale(self, image: Image.Image) -> Image.Image:
        """
        画像をグレースケールに変換する

        後段のパネル合成 (RGB 系) で扱いやすいように、L モードへ変換後 RGB に戻して返す。

        Args:
            image: 元画像

        Returns:
            グレースケール化された RGB 画像 (元画像は変更しない)
        """
        return image.convert("L").convert("RGB")

    def _apply_mosaic(self, image: Image.Image, block: int) -> Image.Image:
        """
        画像にモザイクを適用する

        block 画素四方まで縮小 → 元サイズへ NEAREST で拡大、という古典的手法を用いる。
        block が画像サイズ以上の場合はモザイク効果が消える (実質的に同一画像) が、
        そのまま許容する (例: ラベル "なし" の 300px は 300x300 画像と同サイズ)。

        Args:
            image: 元画像
            block: モザイクの中間解像度 (px)。小さいほど強くかかる。1 以上である必要がある。

        Returns:
            モザイク適用後の新しい画像 (元画像は変更しない)

        Raises:
            ValueError: block が 1 未満の場合
        """
        if block < 1:
            raise ValueError(f"mosaic block は 1 以上で指定してください: {block}")

        orig_size: tuple[int, int] = image.size
        # 中間解像度は (block, block) ではなくアスペクト比を保つよう調整する
        # 全ジャケットは正方形 (300x300) 想定のため通常は (block, block) と同等
        scale_w: int = max(1, min(block, orig_size[0]))
        scale_h: int = max(1, min(block, orig_size[1]))

        small: Image.Image = image.resize(
            (scale_w, scale_h), resample=Image.Resampling.NEAREST
        )
        return small.resize(orig_size, resample=Image.Resampling.NEAREST)

    # --------------------------------------------------
    # パネルグリッド合成
    # --------------------------------------------------
    def _overlay_panels(
        self,
        image: Image.Image,
        panel_count: int,
        cleared_indices: set[int],
    ) -> Image.Image:
        """
        画像の上に N x N のパネルグリッドを重ね、未クリアのセルを塗りつぶして番号を描画する

        セル割り付けは左上から右下へ row-major (1行目 → 2行目 → …)。
        画像サイズが grid 数で割り切れない場合は端数ピクセルを最終行/列に寄せる。

        Args:
            image: 効果適用済みの元画像 (RGB モード前提)
            panel_count: パネルの総数 (平方数)
            cleared_indices: クリア済みセルの 0-origin index 集合 (これらは塗らない)

        Returns:
            パネル合成後の新しい画像 (RGB)

        Raises:
            ValueError: panel_count が平方数でない、または cleared_indices が範囲外
        """
        grid: int = int(math.isqrt(panel_count))
        if grid * grid != panel_count:
            raise ValueError(
                f"panel_count は平方数 (N x N) で指定してください: {panel_count}"
            )
        if any(idx < 0 or idx >= panel_count for idx in cleared_indices):
            raise ValueError(
                f"cleared_indices は [0, {panel_count}) の範囲内で指定してください: "
                f"{sorted(cleared_indices)}"
            )

        # 入力画像を破壊しないようコピーしてから上書きする
        canvas: Image.Image = image.copy()
        draw: ImageDraw.ImageDraw = ImageDraw.Draw(canvas)
        font: _AnyFont = ImageFont.load_default()

        width, height = canvas.size
        # 端数ピクセルが出ても全画素が必ずいずれかのセルに含まれるよう、
        # 最終行/列の境界はそれぞれ width / height ぴったりに固定する
        x_edges: list[int] = [(width * i) // grid for i in range(grid + 1)]
        y_edges: list[int] = [(height * i) // grid for i in range(grid + 1)]

        for row in range(grid):
            for col in range(grid):
                index: int = row * grid + col
                if index in cleared_indices:
                    continue

                left, right = x_edges[col], x_edges[col + 1]
                top, bottom = y_edges[row], y_edges[row + 1]

                # パネル本体 (塗りつぶし + 細い縁取り)
                draw.rectangle(
                    (left, top, right - 1, bottom - 1),
                    fill=self._PANEL_FILL_COLOR,
                    outline=self._PANEL_BORDER_COLOR,
                    width=self._PANEL_BORDER_WIDTH,
                )

                # パネル番号 (1-origin で人間に分かりやすく)
                self._draw_panel_label(
                    draw=draw,
                    font=font,
                    label=str(index + 1),
                    cell=(left, top, right, bottom),
                )

        return canvas

    def _draw_panel_label(
        self,
        draw: ImageDraw.ImageDraw,
        font: _AnyFont,
        label: str,
        cell: tuple[int, int, int, int],
    ) -> None:
        """
        セルの中央にパネル番号を描画する補助メソッド

        Pillow のデフォルトフォントは bbox がやや特殊なため、`textbbox` で計測してから
        中央寄せで配置する。フォントサイズを変えられない代わりに描画安定性を優先する。

        Args:
            draw: 親キャンバスに紐づく ImageDraw
            font: 利用するフォント
            label: 描画する文字列
            cell: (left, top, right, bottom) のセル矩形
        """
        left, top, right, bottom = cell
        # textbbox は (x0, y0, x1, y1) を返す。anchor 指定なしの基準点 (0, 0) で計測。
        # 戻り値は float になる場合があるため整数座標に変換する。
        bbox = draw.textbbox((0, 0), label, font=font)
        text_left: int = int(bbox[0])
        text_top: int = int(bbox[1])
        text_w: int = int(bbox[2]) - text_left
        text_h: int = int(bbox[3]) - text_top

        cell_w: int = right - left
        cell_h: int = bottom - top
        x: int = left + (cell_w - text_w) // 2 - text_left
        y: int = top + (cell_h - text_h) // 2 - text_top

        draw.text((x, y), label, fill=self._PANEL_TEXT_COLOR, font=font)

    # --------------------------------------------------
    # 公開 API
    # --------------------------------------------------
    def compose(
        self,
        song_name: str,
        panel_count: int,
        cleared_indices: set[int],
        rotation_angle: Optional[int],
        grayscale: bool,
        mosaic_block: int,
    ) -> BytesIO:
        """
        楽曲ジャケットにエフェクトを適用し、未クリアパネルで覆った PNG を返す

        処理順序 (ARCHITECTURE.md「パネル画像合成」節準拠):
            1. 元画像を読み込む
            2. rotation_angle が指定されていればその角度で回転 (None ならスキップ)
            3. grayscale=True ならグレースケール化
            4. mosaic_block でモザイク
            5. パネルグリッド合成 (cleared_indices のセルは未塗りで透過)

        Why rotation_angle: セッション間で同じ角度を再現するため、角度決定 (cog 層で
        `pick_rotation_angle` を 1 度だけ呼ぶ) と適用 (本メソッドへの引数) を分離する。
        以前は bool フラグでランダム選択していたため、`compose` を複数回呼ぶと毎回
        違う角度になりセッション内で画像の向きが変動するバグがあった。

        Args:
            song_name: 楽曲名 (`Song.name` と一致するもの)
            panel_count: パネルの総数 (平方数)。`SessionConfig.allowed_panel_counts` 準拠を想定
            cleared_indices: クリア済みパネルの 0-origin index 集合
            rotation_angle: 回転角度 (度)。`None` なら回転なし
            grayscale: グレースケール化を適用するか
            mosaic_block: モザイクの中間解像度 (1 以上)

        Returns:
            PNG 形式の BytesIO (シーク位置は先頭。`discord.File(..., filename="...")` に渡せる)

        Raises:
            FileNotFoundError: 楽曲画像が見つからない場合 (`_load_image` 由来)
            ValueError: panel_count が平方数でない / mosaic_block が 1 未満 /
                cleared_indices が範囲外 の場合
        """
        # 入力バリデーション (画像読み込み前にチェックして早期失敗)
        if mosaic_block < 1:
            raise ValueError(
                f"mosaic_block は 1 以上で指定してください: {mosaic_block}"
            )

        image: Image.Image = self._load_image(song_name)

        if rotation_angle is not None:
            image = self._apply_rotation(image, angle=rotation_angle)
        if grayscale:
            image = self._apply_grayscale(image)
        image = self._apply_mosaic(image, block=mosaic_block)

        composed: Image.Image = self._overlay_panels(
            image=image,
            panel_count=panel_count,
            cleared_indices=cleared_indices,
        )

        buffer: BytesIO = BytesIO()
        composed.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer
