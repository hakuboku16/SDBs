"""
task.py のユニットテスト

`Task` データクラスの初期化バリデーションと、
進捗・クリア判定 (`increment` / `set_progress`)、
description 整形 (`format_description`) の振る舞いを検証します。
"""

import pytest

from tests.conftest import make_task as _t


# ==================================================
# 初期化
# ==================================================
class TestTaskInit:
    """
    `Task.__init__` / `__post_init__` の挙動
    """

    def test_default_progress_fields(self):
        """
        current / cleared を省略した場合、0 / False になる
        """
        task = _t(type="level", set_value=3, value=5)
        assert task.type == "level"
        assert task.set_value == 3
        assert task.value == 5
        assert task.current == 0
        assert task.cleared is False

    def test_value_can_be_complex_object(self):
        """
        value には JSON 由来の任意の構造 (list / dict / None) を格納できる
        """
        task1 = _t(type="title_include", set_value=2, value=["a", "b"])
        assert task1.value == ["a", "b"]

        task2 = _t(type="level_total", set_value=30, value=None)
        assert task2.value is None

        task3 = _t(type="time_below", set_value=1, value={"range": [100, 130]})
        assert task3.value == {"range": [100, 130]}

    def test_set_value_zero_raises(self):
        """
        set_value が 0 なら ValueError
        """
        with pytest.raises(ValueError, match="set_value"):
            _t(type="level", set_value=0, value=5)

    def test_set_value_negative_raises(self):
        """
        set_value が負なら ValueError
        """
        with pytest.raises(ValueError, match="set_value"):
            _t(type="level", set_value=-1, value=5)

    def test_current_negative_raises(self):
        """
        current が負なら ValueError
        """
        with pytest.raises(ValueError, match="current"):
            _t(type="level", set_value=3, value=5, current=-1)

    def test_cleared_is_synced_when_current_already_at_set_value(self):
        """
        初期化時に current >= set_value なら cleared を True に揃える
        """
        task = _t(type="level", set_value=3, value=5, current=3)
        assert task.cleared is True

    def test_cleared_is_synced_when_current_exceeds_set_value(self):
        """
        初期化時に current > set_value でも cleared を True に揃える
        """
        task = _t(type="level", set_value=3, value=5, current=10)
        assert task.cleared is True

    def test_invalid_play_quality_raises(self):
        """
        play_quality が AC/FC/プレイ 以外なら ValueError
        """
        with pytest.raises(ValueError, match="play_quality"):
            _t(
                type="level",
                set_value=1,
                value=5,
                play_quality="UNKNOWN",  # type: ignore[arg-type]
            )


# ==================================================
# increment
# ==================================================
class TestTaskIncrement:
    """
    `Task.increment` の挙動
    """

    def test_increment_increases_current(self):
        """
        increment で current が +1 される
        """
        task = _t(type="level", set_value=3, value=5)
        task.increment()
        assert task.current == 1
        assert task.cleared is False

    def test_increment_returns_false_until_cleared(self):
        """
        まだクリアしていない呼び出しは False を返す
        """
        task = _t(type="level", set_value=3, value=5)
        assert task.increment() is False
        assert task.increment() is False

    def test_increment_returns_true_on_clear_transition(self):
        """
        ちょうどクリアになった呼び出しのみ True を返す
        """
        task = _t(type="level", set_value=3, value=5)
        assert task.increment() is False  # 1
        assert task.increment() is False  # 2
        assert task.increment() is True   # 3 → cleared
        assert task.cleared is True

    def test_increment_is_noop_when_already_cleared(self):
        """
        既にクリア済みなら increment は何もしない
        """
        task = _t(type="level", set_value=2, value=5)
        task.increment()
        task.increment()
        assert task.cleared is True
        assert task.current == 2

        result = task.increment()
        assert result is False
        assert task.current == 2  # 据え置き

    def test_increment_clear_transition_only_once(self):
        """
        クリア境界をまたぐ呼び出しは 1 回だけ True を返す
        """
        task = _t(type="level", set_value=1, value=5)
        assert task.increment() is True
        assert task.increment() is False  # 既にクリア済み


# ==================================================
# set_progress
# ==================================================
class TestTaskSetProgress:
    """
    `Task.set_progress` の挙動 (累積系タスク向け)
    """

    def test_set_progress_updates_current(self):
        """
        絶対値で current が更新される
        """
        task = _t(type="level_total", set_value=30, value=None)
        task.set_progress(12)
        assert task.current == 12
        assert task.cleared is False

    def test_set_progress_to_zero(self):
        """
        0 に戻すこともできる
        """
        task = _t(type="level_total", set_value=30, value=None)
        task.set_progress(15)
        task.set_progress(0)
        assert task.current == 0
        assert task.cleared is False

    def test_set_progress_clears_when_meets_set_value(self):
        """
        set_value 到達で cleared = True、True を返す
        """
        task = _t(type="level_total", set_value=30, value=None)
        result = task.set_progress(30)
        assert result is True
        assert task.cleared is True

    def test_set_progress_clears_when_exceeds_set_value(self):
        """
        set_value 超過でも cleared = True、True を返す
        """
        task = _t(type="result_combo_total", set_value=3000, value=None)
        result = task.set_progress(5000)
        assert result is True
        assert task.cleared is True
        assert task.current == 5000

    def test_set_progress_noop_clear_returns_false(self):
        """
        既にクリア済みのタスクで再度クリア水準を設定しても True は返さない
        (新規クリア遷移ではないため)
        """
        task = _t(type="level_total", set_value=30, value=None)
        task.set_progress(30)  # ここで True
        result = task.set_progress(40)
        assert result is False
        assert task.cleared is True
        assert task.current == 40

    def test_set_progress_negative_raises(self):
        """
        負の値を指定すると ValueError
        """
        task = _t(type="level_total", set_value=30, value=None)
        with pytest.raises(ValueError, match="value"):
            task.set_progress(-1)


# ==================================================
# format_description
# ==================================================
class TestTaskFormatDescription:
    """
    `Task.format_description` の placeholder 置換挙動
    """

    def test_replace_value_set_play_for_list_value(self):
        """
        value がリストの場合 ``"(a, b, c)"`` 形式で整形され、
        set / play も実値に置換される
        """
        task = _t(
            type="title_include",
            set_value=2,
            value=["a", "b", "c"],
            play_quality="AC",
            description_template="楽曲名にvalueのすべてが含まれる楽曲をset回play",
        )
        assert (
            task.format_description()
            == "楽曲名に(a, b, c)のすべてが含まれる楽曲を2回AC"
        )

    def test_replace_value_for_int_value(self):
        """
        value が int の場合は str() で直接置換される
        """
        task = _t(
            type="title_len_below",
            set_value=4,
            value=3,
            play_quality="FC",
            description_template="楽曲名がvalue文字以下の曲をset回play",
        )
        assert task.format_description() == "楽曲名が3文字以下の曲を4回FC"

    def test_replace_value_for_float_value(self):
        """
        value が float の場合も str() で直接置換される
        """
        task = _t(
            type="notes_density_below",
            set_value=2,
            value=0.8,
            play_quality="プレイ",
            description_template="ノーツ密度がvalue[notes/s]以下の譜面を持つ楽曲をset回play",
        )
        assert (
            task.format_description()
            == "ノーツ密度が0.8[notes/s]以下の譜面を持つ楽曲を2回プレイ"
        )

    def test_replace_when_value_is_none(self):
        """
        value が None なら value placeholder は空文字に置換される
        (累積系の description には value placeholder が出現しない想定)
        """
        task = _t(
            type="level_total",
            set_value=30,
            value=None,
            play_quality="プレイ",
            description_template="playした譜面のレベルの合計がset",
        )
        assert task.format_description() == "プレイした譜面のレベルの合計が30"

    def test_replace_play_with_quality_label(self):
        """
        play は ``play_quality`` の値 (AC/FC/プレイ) に置き換えられる
        """
        ac_task = _t(
            type="level",
            set_value=3,
            value=5,
            play_quality="AC",
            description_template="Lv.valueの譜面を持つ楽曲をset回play",
        )
        assert ac_task.format_description() == "Lv.5の譜面を持つ楽曲を3回AC"

        fc_task = _t(
            type="level",
            set_value=3,
            value=5,
            play_quality="FC",
            description_template="Lv.valueの譜面を持つ楽曲をset回play",
        )
        assert fc_task.format_description() == "Lv.5の譜面を持つ楽曲を3回FC"
