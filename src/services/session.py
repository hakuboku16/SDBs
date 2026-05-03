"""
セッション関連のドメインモデルを提供するモジュール

本モジュールは Discord に依存しないプレーンなデータモデルのみを提供します。
タイマー処理 (`asyncio` を用いた30分自動終了など) は Discord 依存があるため、
ステップ 4 以降の Bot 層で扱います。
"""

from dataclasses import dataclass, field
from datetime import datetime

from src.services.task import Task


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


# ==================================================
# 回答履歴モデル
# ==================================================
@dataclass
class AnswerRecord:
    """
    プレイヤーが /answer で行った 1 件の回答を表すデータクラス

    `/answer` は ephemeral で本人にのみ ○/× を返しますが、`/end` 時の集計用に
    全回答を `Session` 側で蓄積します。

    Attributes:
        user_id: 回答した Discord ユーザー ID
        song_name: 回答した楽曲名
        correct: 正解だったかどうか
        answered_at: 回答時刻
    """

    user_id: int
    song_name: str
    correct: bool
    answered_at: datetime


# ==================================================
# セッションモデル
# ==================================================
@dataclass
class Session:
    """
    1 件の進行中ゲームセッションを表すデータモデル

    `SessionManager` がシングルトンとして `_current: Session | None` を保持します。
    タイマー処理は持たず、本モデルはあくまでデータ集約と進捗参照に専念します。

    Attributes:
        song_name: 正解 (パネルに隠した楽曲) の楽曲名
        panel_count: パネル枚数 (4 / 9 / 16 / 25 のいずれか)
        tasks: TaskGenerator が生成した N 個のお題
        channel_id: セッションを開始した Discord チャンネル ID
        owner_id: セッションを開始した Discord ユーザー ID
        started_at: セッション開始時刻
        rotate: 画像合成時に 90/180/270 度のランダム回転を行うか
        grayscale: 画像合成時にグレースケール化するか
        mosaic_block: モザイクの block 画素数 (大きいほど弱い)
        play_records: /play で蓄積するプレイ履歴 (時系列)
        answer_records: /answer の全回答履歴 (時系列)
    """

    song_name: str
    panel_count: int
    tasks: list[Task]
    channel_id: int
    owner_id: int
    started_at: datetime
    rotate: bool = False
    grayscale: bool = False
    mosaic_block: int = 300
    play_records: list[PlayRecord] = field(default_factory=list)
    answer_records: list[AnswerRecord] = field(default_factory=list)

    def __post_init__(self) -> None:
        """
        フィールドの整合性を検証する

        Raises:
            ValueError: panel_count とタスク数の不一致、mosaic_block 非正値、
                時刻が tz-naive で他と混在する等の不整合がある場合
        """
        if self.panel_count < 1:
            raise ValueError(
                f"panel_count は 1 以上である必要があります: {self.panel_count}"
            )
        if len(self.tasks) != self.panel_count:
            raise ValueError(
                "panel_count と tasks 数が一致しません: "
                f"panel_count={self.panel_count}, tasks={len(self.tasks)}"
            )
        if self.mosaic_block <= 0:
            raise ValueError(
                f"mosaic_block は正の整数である必要があります: {self.mosaic_block}"
            )

    # --------------------------------------------------
    # 進捗参照
    # --------------------------------------------------
    def cleared_panel_indices(self) -> set[int]:
        """
        クリア済みタスクの index 集合を返す (画像合成の `cleared_indices` 引数用)

        Returns:
            ``tasks`` 内でクリア済みの位置を示す 0-origin の index 集合
        """
        return {idx for idx, task in enumerate(self.tasks) if task.cleared}

    def is_all_cleared(self) -> bool:
        """
        全タスクがクリア済みかを返す
        """
        return all(task.cleared for task in self.tasks)

    # --------------------------------------------------
    # 履歴追加
    # --------------------------------------------------
    def add_play(self, record: PlayRecord) -> None:
        """
        プレイ履歴を追加する (タスク評価は呼び出し側で行う前提)
        """
        self.play_records.append(record)

    def add_answer(self, record: AnswerRecord) -> None:
        """
        回答履歴を追加する
        """
        self.answer_records.append(record)
