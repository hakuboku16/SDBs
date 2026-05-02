"""
セッション関連のドメインモデルを提供するモジュール

本モジュールは Discord に依存しないプレーンなデータモデルのみを提供します。
セッション本体 (`Session`) と `SessionManager` はステップ 2.5 で追加します。
"""

from dataclasses import dataclass


# ==================================================
# プレイ履歴モデル
# ==================================================
@dataclass
class PlayRecord:
    """
    プレイヤーが /play で入力した 1 件のリザルトを表すデータクラス

    バリデーション (charming / combo の自然数チェック等) は cog 層で行うため、
    本モデル自体は値の妥当性を検証しません。

    Attributes:
        song_name: プレイした楽曲名 (`Song.name` と一致)
        difficulty: 難易度 (例: "Easy" / "Normal" / "Hard" / "Extra")
        charming: リザルト画面の charming 数
        combo: リザルト画面の combo 数
    """

    song_name: str
    difficulty: str
    charming: int
    combo: int
