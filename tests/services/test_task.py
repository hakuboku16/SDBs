"""
task.py のユニットテスト

`Task` データクラスの初期化バリデーションと、
進捗・クリア判定 (`increment` / `set_progress`) の振る舞いを検証します。
"""

import pytest

from src.services.task import Task


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
        task = Task(type="level", set_value=3, value=5)
        assert task.type == "level"
        assert task.set_value == 3
        assert task.value == 5
        assert task.current == 0
        assert task.cleared is False

    def test_value_can_be_complex_object(self):
        """
        value には JSON 由来の任意の構造 (list / dict / None) を格納できる
        """
        task1 = Task(type="title_include", set_value=2, value=["a", "b"])
        assert task1.value == ["a", "b"]

        task2 = Task(type="level_total", set_value=30, value=None)
        assert task2.value is None

        task3 = Task(type="time_below", set_value=1, value={"range": [100, 130]})
        assert task3.value == {"range": [100, 130]}

    def test_set_value_zero_raises(self):
        """
        set_value が 0 なら ValueError
        """
        with pytest.raises(ValueError, match="set_value"):
            Task(type="level", set_value=0, value=5)

    def test_set_value_negative_raises(self):
        """
        set_value が負なら ValueError
        """
        with pytest.raises(ValueError, match="set_value"):
            Task(type="level", set_value=-1, value=5)

    def test_current_negative_raises(self):
        """
        current が負なら ValueError
        """
        with pytest.raises(ValueError, match="current"):
            Task(type="level", set_value=3, value=5, current=-1)

    def test_cleared_is_synced_when_current_already_at_set_value(self):
        """
        初期化時に current >= set_value なら cleared を True に揃える
        """
        task = Task(type="level", set_value=3, value=5, current=3)
        assert task.cleared is True

    def test_cleared_is_synced_when_current_exceeds_set_value(self):
        """
        初期化時に current > set_value でも cleared を True に揃える
        """
        task = Task(type="level", set_value=3, value=5, current=10)
        assert task.cleared is True


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
        task = Task(type="level", set_value=3, value=5)
        task.increment()
        assert task.current == 1
        assert task.cleared is False

    def test_increment_returns_false_until_cleared(self):
        """
        まだクリアしていない呼び出しは False を返す
        """
        task = Task(type="level", set_value=3, value=5)
        assert task.increment() is False
        assert task.increment() is False

    def test_increment_returns_true_on_clear_transition(self):
        """
        ちょうどクリアになった呼び出しのみ True を返す
        """
        task = Task(type="level", set_value=3, value=5)
        assert task.increment() is False  # 1
        assert task.increment() is False  # 2
        assert task.increment() is True   # 3 → cleared
        assert task.cleared is True

    def test_increment_is_noop_when_already_cleared(self):
        """
        既にクリア済みなら increment は何もしない
        """
        task = Task(type="level", set_value=2, value=5)
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
        task = Task(type="level", set_value=1, value=5)
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
        task = Task(type="level_total", set_value=30, value=None)
        task.set_progress(12)
        assert task.current == 12
        assert task.cleared is False

    def test_set_progress_to_zero(self):
        """
        0 に戻すこともできる
        """
        task = Task(type="level_total", set_value=30, value=None)
        task.set_progress(15)
        task.set_progress(0)
        assert task.current == 0
        assert task.cleared is False

    def test_set_progress_clears_when_meets_set_value(self):
        """
        set_value 到達で cleared = True、True を返す
        """
        task = Task(type="level_total", set_value=30, value=None)
        result = task.set_progress(30)
        assert result is True
        assert task.cleared is True

    def test_set_progress_clears_when_exceeds_set_value(self):
        """
        set_value 超過でも cleared = True、True を返す
        """
        task = Task(type="result_combo_total", set_value=3000, value=None)
        result = task.set_progress(5000)
        assert result is True
        assert task.cleared is True
        assert task.current == 5000

    def test_set_progress_noop_clear_returns_false(self):
        """
        既にクリア済みのタスクで再度クリア水準を設定しても True は返さない
        (新規クリア遷移ではないため)
        """
        task = Task(type="level_total", set_value=30, value=None)
        task.set_progress(30)  # ここで True
        result = task.set_progress(40)
        assert result is False
        assert task.cleared is True
        assert task.current == 40

    def test_set_progress_negative_raises(self):
        """
        負の値を指定すると ValueError
        """
        task = Task(type="level_total", set_value=30, value=None)
        with pytest.raises(ValueError, match="value"):
            task.set_progress(-1)
