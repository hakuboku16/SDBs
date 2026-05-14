"""
タスク (お題) のドメインモデルを提供するモジュール

タスクは「特定の条件を満たすプレイを set_value 回行う」という単位を表します。
本モジュールはデータ構造と進捗・クリア判定のみを保持し、
お題条件 (type) の評価ロジックは TaskEvaluator が担います。
"""

from dataclasses import dataclass
from typing import Any, Literal

# プレイ品質: お題ごとに「どんなプレイをカウントするか」を表す
# - "AC": charming 数が当該譜面の NOTES 数と一致するプレイ (All Charming)
# - "FC": combo 数が当該譜面の NOTES 数と一致するプレイ (Full Combo)
# - "プレイ": 任意のプレイ (フィルタなし)
PlayQuality = Literal["AC", "FC", "プレイ"]

# 有効値の集合 (バリデーション用に列挙)
_VALID_PLAY_QUALITIES: frozenset[str] = frozenset(("AC", "FC", "プレイ"))


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
        play_quality: カウント対象とするプレイ品質 (AC / FC / プレイ)
        description_template: all_topics.json から引き継いだ description テンプレート文字列
            (例: "楽曲名にvalueのすべてが含まれる楽曲をset回play")
        current: 現在の達成回数 (0 以上)
        cleared: クリア済みかどうか
    """

    type: str
    set_value: int
    value: Any
    play_quality: PlayQuality
    description_template: str
    current: int = 0
    cleared: bool = False

    def __post_init__(self) -> None:
        """
        フィールドの整合性を検証し、`current` と `cleared` の対応関係を揃える

        Raises:
            ValueError: set_value が 1 未満、current が負、play_quality が不正な場合
        """
        if self.set_value < 1:
            raise ValueError(
                f"set_value は 1 以上である必要があります: {self.set_value}"
            )
        if self.current < 0:
            raise ValueError(
                f"current は 0 以上である必要があります: {self.current}"
            )
        if self.play_quality not in _VALID_PLAY_QUALITIES:
            raise ValueError(
                "play_quality は 'AC' / 'FC' / 'プレイ' のいずれかである必要があります: "
                f"{self.play_quality!r}"
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

    # --------------------------------------------------
    # 表示整形
    # --------------------------------------------------
    def format_description(self) -> str:
        """
        ``description_template`` の placeholder を実値に置換した文字列を返す

        置換規則:
            - ``value`` → ``value`` の整形表現
                * list/tuple は ``"(a, b, c)"`` 形式 (要素を str 化してカンマ区切り)
                * それ以外は ``str()`` で直接文字列化
                * None の場合は空文字 (description にも value placeholder は出現しない想定)
            - ``set``  → ``str(set_value)``
            - ``play`` → ``play_quality`` (AC / FC / プレイ)

        ``str.replace`` で順次置換しているため、置換結果に再度 placeholder と同名の
        部分文字列が含まれてしまうケース (例: value 内に ``"set"`` 等を含む場合)
        は注意が必要だが、all_topics.json の現仕様では発生しない。

        Returns:
            placeholder を実値に置き換えた description 文字列
        """
        text = self.description_template
        text = text.replace("value", _format_value(self.value))
        text = text.replace("set", str(self.set_value))
        text = text.replace("play", self.play_quality)
        return text


# ==================================================
# value 整形ヘルパー
# ==================================================
def _format_value(value: Any) -> str:
    """
    `Task.value` を description 内で表示するための文字列に整形する

    - list / tuple: ``"(a, b, c)"`` 形式 (要素を str 化してカンマ区切り)
    - None: 空文字 (description に value placeholder が出現しない種別)
    - その他 (int / float / str): ``str()`` で直接文字列化

    Args:
        value: `Task.value` に格納されている任意の値

    Returns:
        description 表示用に整形した文字列
    """
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "(" + ", ".join(str(v) for v in value) + ")"
    return str(value)
