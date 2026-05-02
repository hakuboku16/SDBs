"""
タスク (お題) のドメインモデルを提供するモジュール

タスクは「特定の条件を満たすプレイを set_value 回行う」という単位を表します。
本モジュールはデータ構造と進捗・クリア判定のみを保持し、
お題条件 (type) の評価ロジックは TaskEvaluator が担います。
"""

from dataclasses import dataclass
from typing import Any


# ==================================================
# タスクモデル
# ==================================================
@dataclass
class Task:
    """
    1 件のお題を表すデータクラス

    Attributes:
        type: お題の種別 (例: "title_include", "level", "level_total")
        set_value: クリアまでに必要な達成回数 (1 以上)
        value: お題ごとに固有のパラメータ。type により構造が変わる
            (例: title_include なら ["a", "b"]、level なら 5、level_total なら None)
        current: 現在の達成回数 (0 以上)
        cleared: クリア済みかどうか
    """

    type: str
    set_value: int
    value: Any
    current: int = 0
    cleared: bool = False

    def __post_init__(self) -> None:
        """
        フィールドの整合性を検証し、`current` と `cleared` の対応関係を揃える

        Raises:
            ValueError: set_value が 1 未満、または current が負の場合
        """
        if self.set_value < 1:
            raise ValueError(
                f"set_value は 1 以上である必要があります: {self.set_value}"
            )
        if self.current < 0:
            raise ValueError(
                f"current は 0 以上である必要があります: {self.current}"
            )
        # 初期化値が既に達成水準に到達していれば cleared を True に揃える
        if self.current >= self.set_value:
            self.cleared = True

    # --------------------------------------------------
    # 進捗更新
    # --------------------------------------------------
    def increment(self) -> bool:
        """
        進捗を 1 増やし、必要に応じてクリア状態を更新する

        既にクリア済みの場合は何もしません (current は据え置き)。

        Returns:
            このメソッド呼び出しによって新たにクリアに到達した場合 True、
            それ以外 (進捗のみ / 既にクリア済み) は False
        """
        if self.cleared:
            return False

        self.current += 1
        if self.current >= self.set_value:
            self.cleared = True
            return True
        return False

    def set_progress(self, value: int) -> bool:
        """
        進捗を絶対値で更新する (累積系タスク向け)

        `level_total` / `result_charming_total` / `result_combo_total` のように
        全プレイ履歴から都度再計算する種別を想定しています。

        Args:
            value: 設定する進捗値 (0 以上)

        Returns:
            このメソッド呼び出しによって新たにクリアに到達した場合 True、
            それ以外 (進捗のみ更新 / 元々クリア済みのまま) は False

        Raises:
            ValueError: value が負の場合
        """
        if value < 0:
            raise ValueError(f"value は 0 以上である必要があります: {value}")

        was_cleared = self.cleared
        self.current = value
        if self.current >= self.set_value:
            self.cleared = True
        return self.cleared and not was_cleared
