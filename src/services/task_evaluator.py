"""
お題 (Task) の評価ロジックを提供するモジュール

`TaskEvaluator` は `Task.type` ごとに評価関数を辞書登録した戦略パターン実装で、
`/play` で受け取った `PlayRecord` を踏まえて `Task.current` の新しい値を算出します。

評価方針:

- マッチ系 (大半の type)
    最新 `play_record` が条件を満たせば ``current + 1`` を返し、
    満たさなければ据え置きの ``current`` を返します。
- 累積系 (``level_total`` / ``result_charming_total`` / ``result_combo_total``)
    ``all_plays`` 全体から合計値を再計算して返します。

呼び出し側は返値を ``Task.set_progress(new_current)`` に渡して進捗を反映します。
"""

from typing import Any, Callable

from src.services.session import PlayRecord
from src.services.song_repository import Song, SongRepository
from src.services.task import Task

# 評価関数シグネチャ (内部用エイリアス)
_EvaluatorFn = Callable[
    [Task, PlayRecord, list[PlayRecord], SongRepository], int
]


# ==================================================
# TaskEvaluator
# ==================================================
class TaskEvaluator:
    """
    お題タイプごとの評価関数を辞書登録し、`evaluate` で新 ``current`` を算出する評価器

    インスタンスは状態を持たず、複数セッションで使い回し可能です。
    """

    def __init__(self) -> None:
        # type 文字列 → 評価関数の辞書 (戦略パターン)
        self._evaluators: dict[str, _EvaluatorFn] = {
            # title_*
            "title_include": self._eval_title_include,
            "title_startswith": self._eval_title_startswith,
            "title_endswith": self._eval_title_endswith,
            "title_len_below": self._eval_title_len_below,
            "title_len_above": self._eval_title_len_above,
            "title_blank": self._eval_title_blank,
            # 難易度・レベル
            "difficult": self._eval_difficult,
            "level": self._eval_level,
            # 累積系
            "level_total": self._eval_level_total,
            "result_charming_total": self._eval_result_charming_total,
            "result_combo_total": self._eval_result_combo_total,
            # notes_*
            "notes_below": self._eval_notes_below,
            "notes_above": self._eval_notes_above,
            "notes_density_below": self._eval_notes_density_below,
            "notes_density_above": self._eval_notes_density_above,
            "notes_endswith": self._eval_notes_endswith,
            # composer / featuring
            "composer_name_startswith": self._eval_composer_name_startswith,
            "composer_name_endswith": self._eval_composer_name_endswith,
            "composer_members": self._eval_composer_members,
            "featuring": self._eval_featuring,
            # time
            "time_below": self._eval_time_below,
            "time_above": self._eval_time_above,
            # 楽曲メタ
            "version": self._eval_version,
            "book": self._eval_book,
            "shelf": self._eval_shelf,
        }

    # --------------------------------------------------
    # 公開 API
    # --------------------------------------------------
    def evaluate(
        self,
        task: Task,
        play_record: PlayRecord,
        all_plays: list[PlayRecord],
        song_repo: SongRepository,
    ) -> int:
        """
        最新 ``play_record`` を考慮した ``task.current`` の新しい値を返す

        マッチ系は「条件成立で +1、不成立で据え置き」、
        累積系は ``all_plays`` から再計算した値を返します。

        Args:
            task: 対象タスク
            play_record: 直近に追加された 1 件のプレイ記録
            all_plays: 現セッションの全プレイ記録 (``play_record`` 自身も含まれている前提)
            song_repo: 楽曲メタ解決に用いるリポジトリ

        Returns:
            適用すべき新しい ``current`` 値 (``task.current`` 以上、累積系では大きく変動しうる)

        Raises:
            ValueError: 未知の type、または楽曲が `SongRepository` に存在しない場合等
        """
        fn = self._evaluators.get(task.type)
        if fn is None:
            raise ValueError(f"未対応のお題タイプです: {task.type}")
        return fn(task, play_record, all_plays, song_repo)

    def supported_types(self) -> frozenset[str]:
        """
        評価対応している type の集合 (テスト・診断用)
        """
        return frozenset(self._evaluators.keys())

    # --------------------------------------------------
    # 内部ヘルパー
    # --------------------------------------------------
    @staticmethod
    def _matched(task: Task, matched: bool) -> int:
        """マッチ判定結果から新 current を算出する小ヘルパー"""
        return task.current + 1 if matched else task.current

    @staticmethod
    def _required_song(song_repo: SongRepository, name: str) -> Song:
        """SongRepository から楽曲を取得 (見つからなければ ValueError)"""
        song = song_repo.find_by_name(name)
        if song is None:
            raise ValueError(f"楽曲が SongRepository に存在しません: {name!r}")
        return song

    @staticmethod
    def _required_level(song: Song, difficulty: str) -> int:
        """指定難易度のレベルを取得 (なければ ValueError)"""
        level = song.levels.get(difficulty)
        if level is None:
            raise ValueError(
                f"楽曲 '{song.name}' に難易度 '{difficulty}' のレベル定義がありません"
            )
        return level

    @staticmethod
    def _required_notes(song: Song, difficulty: str) -> int:
        """指定難易度のノーツ数を取得 (なければ ValueError)"""
        notes = song.notes.get(difficulty)
        if notes is None:
            raise ValueError(
                f"楽曲 '{song.name}' に難易度 '{difficulty}' のノーツ定義がありません"
            )
        return notes

    @staticmethod
    def _to_str_list(value: Any) -> list[str]:
        """`value` を `list[str]` として取り出す (型不一致なら ValueError)"""
        if not isinstance(value, list):
            raise ValueError(f"value はリスト形式である必要があります: {value!r}")
        return [str(v) for v in value]

    @staticmethod
    def _to_int(value: Any) -> int:
        """`value` を int として取り出す (型不一致なら ValueError)"""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"value は数値である必要があります: {value!r}")
        return int(value)

    @staticmethod
    def _to_float(value: Any) -> float:
        """`value` を float として取り出す (型不一致なら ValueError)"""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"value は数値である必要があります: {value!r}")
        return float(value)

    # --------------------------------------------------
    # title_*
    # --------------------------------------------------
    def _eval_title_include(
        self, task: Task, play_record: PlayRecord, all_plays, song_repo
    ) -> int:
        """楽曲名に value のすべての文字 (大文字小文字無視) が含まれるか"""
        chars = [c.casefold() for c in self._to_str_list(task.value)]
        title = play_record.song_name.casefold()
        return self._matched(task, all(c in title for c in chars))

    def _eval_title_startswith(
        self, task: Task, play_record: PlayRecord, all_plays, song_repo
    ) -> int:
        """楽曲名が value のいずれかの文字 (大文字小文字無視) で始まるか"""
        chars = [c.casefold() for c in self._to_str_list(task.value)]
        title = play_record.song_name.casefold()
        return self._matched(task, any(title.startswith(c) for c in chars))

    def _eval_title_endswith(
        self, task: Task, play_record: PlayRecord, all_plays, song_repo
    ) -> int:
        """楽曲名が value のいずれかの文字 (大文字小文字無視) で終わるか"""
        chars = [c.casefold() for c in self._to_str_list(task.value)]
        title = play_record.song_name.casefold()
        return self._matched(task, any(title.endswith(c) for c in chars))

    def _eval_title_len_below(
        self, task: Task, play_record: PlayRecord, all_plays, song_repo
    ) -> int:
        """楽曲名の長さが value 文字以下か"""
        return self._matched(
            task, len(play_record.song_name) <= self._to_int(task.value)
        )

    def _eval_title_len_above(
        self, task: Task, play_record: PlayRecord, all_plays, song_repo
    ) -> int:
        """楽曲名の長さが value 文字以上か"""
        return self._matched(
            task, len(play_record.song_name) >= self._to_int(task.value)
        )

    def _eval_title_blank(
        self, task: Task, play_record: PlayRecord, all_plays, song_repo
    ) -> int:
        """楽曲名に含まれる半角スペース数がちょうど value 個か"""
        return self._matched(
            task, play_record.song_name.count(" ") == self._to_int(task.value)
        )

    # --------------------------------------------------
    # 難易度・レベル
    # --------------------------------------------------
    def _eval_difficult(
        self, task: Task, play_record: PlayRecord, all_plays, song_repo
    ) -> int:
        """プレイした難易度が value (難易度名のリスト) に含まれるか"""
        allowed = self._to_str_list(task.value)
        return self._matched(task, play_record.difficulty in allowed)

    def _eval_level(
        self, task: Task, play_record: PlayRecord, all_plays, song_repo
    ) -> int:
        """楽曲が value レベルの譜面を 1 つ以上持つか (任意難易度で OK)"""
        target = self._to_int(task.value)
        song = self._required_song(song_repo, play_record.song_name)
        return self._matched(task, any(lv == target for lv in song.levels.values()))

    # --------------------------------------------------
    # 累積系 (all_plays を毎回再計算)
    # --------------------------------------------------
    def _eval_level_total(
        self, task: Task, play_record: PlayRecord, all_plays, song_repo
    ) -> int:
        """全プレイの (プレイした難易度の) レベル合計"""
        total = 0
        for pr in all_plays:
            song = self._required_song(song_repo, pr.song_name)
            total += self._required_level(song, pr.difficulty)
        return total

    def _eval_result_charming_total(
        self, task: Task, play_record: PlayRecord, all_plays, song_repo
    ) -> int:
        """全プレイの charming 合計"""
        return sum(pr.charming for pr in all_plays)

    def _eval_result_combo_total(
        self, task: Task, play_record: PlayRecord, all_plays, song_repo
    ) -> int:
        """全プレイの combo 合計"""
        return sum(pr.combo for pr in all_plays)

    # --------------------------------------------------
    # notes_*
    # --------------------------------------------------
    def _eval_notes_below(
        self, task: Task, play_record: PlayRecord, all_plays, song_repo
    ) -> int:
        """楽曲がノーツ数 value 以下の譜面を 1 つ以上持つか"""
        threshold = self._to_int(task.value)
        song = self._required_song(song_repo, play_record.song_name)
        return self._matched(
            task, any(n <= threshold for n in song.notes.values())
        )

    def _eval_notes_above(
        self, task: Task, play_record: PlayRecord, all_plays, song_repo
    ) -> int:
        """楽曲がノーツ数 value 以上の譜面を 1 つ以上持つか"""
        threshold = self._to_int(task.value)
        song = self._required_song(song_repo, play_record.song_name)
        return self._matched(
            task, any(n >= threshold for n in song.notes.values())
        )

    def _eval_notes_density_below(
        self, task: Task, play_record: PlayRecord, all_plays, song_repo
    ) -> int:
        """楽曲がノーツ密度 value [notes/s] 以下の譜面を 1 つ以上持つか"""
        threshold = self._to_float(task.value)
        song = self._required_song(song_repo, play_record.song_name)
        if song.time <= 0:
            # 0 除算回避: 演奏時間不定の楽曲は密度判定不能とみなしマッチしない
            return self._matched(task, False)
        return self._matched(
            task, any((n / song.time) <= threshold for n in song.notes.values())
        )

    def _eval_notes_density_above(
        self, task: Task, play_record: PlayRecord, all_plays, song_repo
    ) -> int:
        """楽曲がノーツ密度 value [notes/s] 以上の譜面を 1 つ以上持つか"""
        threshold = self._to_float(task.value)
        song = self._required_song(song_repo, play_record.song_name)
        if song.time <= 0:
            return self._matched(task, False)
        return self._matched(
            task, any((n / song.time) >= threshold for n in song.notes.values())
        )

    def _eval_notes_endswith(
        self, task: Task, play_record: PlayRecord, all_plays, song_repo
    ) -> int:
        """プレイした譜面のノーツ数の一の位が value (1 文字) と一致するか"""
        # 仕様 (all_topics.json): {"candidate": "0123456789", "choice": 1} → list[str] (要素 1)
        digits = self._to_str_list(task.value)
        if len(digits) != 1:
            raise ValueError(
                f"notes_endswith の value は 1 要素のリストである必要があります: {task.value!r}"
            )
        target = int(digits[0])
        song = self._required_song(song_repo, play_record.song_name)
        notes = self._required_notes(song, play_record.difficulty)
        return self._matched(task, (notes % 10) == target)

    # --------------------------------------------------
    # composer / featuring
    # --------------------------------------------------
    def _eval_composer_name_startswith(
        self, task: Task, play_record: PlayRecord, all_plays, song_repo
    ) -> int:
        """楽曲のいずれかのコンポーザー名が value のいずれかの文字で始まるか"""
        chars = [c.casefold() for c in self._to_str_list(task.value)]
        song = self._required_song(song_repo, play_record.song_name)
        composers = [c.casefold() for c in song.composer]
        matched = any(comp.startswith(ch) for comp in composers for ch in chars)
        return self._matched(task, matched)

    def _eval_composer_name_endswith(
        self, task: Task, play_record: PlayRecord, all_plays, song_repo
    ) -> int:
        """楽曲のいずれかのコンポーザー名が value のいずれかの文字で終わるか"""
        chars = [c.casefold() for c in self._to_str_list(task.value)]
        song = self._required_song(song_repo, play_record.song_name)
        composers = [c.casefold() for c in song.composer]
        matched = any(comp.endswith(ch) for comp in composers for ch in chars)
        return self._matched(task, matched)

    def _eval_composer_members(
        self, task: Task, play_record: PlayRecord, all_plays, song_repo
    ) -> int:
        """コンポーザーが複数人いる楽曲か"""
        song = self._required_song(song_repo, play_record.song_name)
        return self._matched(task, len(song.composer) >= 2)

    def _eval_featuring(
        self, task: Task, play_record: PlayRecord, all_plays, song_repo
    ) -> int:
        """フィーチャリング楽曲か (feat. が 1 件以上ある)"""
        song = self._required_song(song_repo, play_record.song_name)
        return self._matched(task, len(song.feat) >= 1)

    # --------------------------------------------------
    # time
    # --------------------------------------------------
    def _eval_time_below(
        self, task: Task, play_record: PlayRecord, all_plays, song_repo
    ) -> int:
        """楽曲の演奏時間が value 秒以下か"""
        threshold = self._to_int(task.value)
        song = self._required_song(song_repo, play_record.song_name)
        return self._matched(task, song.time <= threshold)

    def _eval_time_above(
        self, task: Task, play_record: PlayRecord, all_plays, song_repo
    ) -> int:
        """楽曲の演奏時間が value 秒以上か"""
        threshold = self._to_int(task.value)
        song = self._required_song(song_repo, play_record.song_name)
        return self._matched(task, song.time >= threshold)

    # --------------------------------------------------
    # 楽曲メタ (version / book / shelf)
    # --------------------------------------------------
    def _eval_version(
        self, task: Task, play_record: PlayRecord, all_plays, song_repo
    ) -> int:
        """楽曲のバージョンが value (バージョンのリスト) に含まれるか"""
        allowed = self._to_str_list(task.value)
        song = self._required_song(song_repo, play_record.song_name)
        return self._matched(task, song.version in allowed)

    def _eval_book(
        self, task: Task, play_record: PlayRecord, all_plays, song_repo
    ) -> int:
        """楽曲の book が value (book 名のリスト) に含まれるか"""
        allowed = self._to_str_list(task.value)
        song = self._required_song(song_repo, play_record.song_name)
        return self._matched(task, song.book in allowed)

    def _eval_shelf(
        self, task: Task, play_record: PlayRecord, all_plays, song_repo
    ) -> int:
        """楽曲の shelf が value (shelf 名のリスト) に含まれるか"""
        allowed = self._to_str_list(task.value)
        song = self._required_song(song_repo, play_record.song_name)
        return self._matched(task, song.shelf in allowed)
