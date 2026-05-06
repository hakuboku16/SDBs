"""
session.py のユニットテスト

`PlayRecord` / `AnswerRecord` データクラスと、
`Session` の初期化バリデーション・進捗参照・履歴追加の振る舞いを検証します。
"""

from datetime import datetime, timezone

import pytest

from src.services.session import AnswerRecord, PlayRecord, Session
from src.services.task import Task


# ==================================================
# テスト用ヘルパー
# ==================================================
def _make_task(set_value: int = 1, *, current: int = 0) -> Task:
    """検証ロジックに干渉しないシンプルな Task を作成する"""
    return Task(type="level", set_value=set_value, value=5, current=current)


def _make_session(
    *,
    panel_count: int = 4,
    tasks: list[Task] | None = None,
    rotate: bool = False,
    grayscale: bool = False,
    mosaic_block: int = 300,
) -> Session:
    """テスト用の Session を組み立てる"""
    if tasks is None:
        tasks = [_make_task() for _ in range(panel_count)]
    return Session(
        song_name="Aragami",
        panel_count=panel_count,
        tasks=tasks,
        channel_id=111,
        owner_id=222,
        started_at=datetime(2026, 5, 3, 10, 0, 0, tzinfo=timezone.utc),
        rotate=rotate,
        grayscale=grayscale,
        mosaic_block=mosaic_block,
    )


# ==================================================
# PlayRecord
# ==================================================
class TestPlayRecord:
    """
    `PlayRecord` データクラスの挙動
    """

    def test_fields_are_stored_as_is(self):
        """
        4 つのフィールドがそのまま格納される (バリデーション無し)
        """
        rec = PlayRecord(
            song_name="Magnolia", difficulty="Hard", charming=300, combo=500
        )
        assert rec.song_name == "Magnolia"
        assert rec.difficulty == "Hard"
        assert rec.charming == 300
        assert rec.combo == 500


# ==================================================
# AnswerRecord
# ==================================================
class TestAnswerRecord:
    """
    `AnswerRecord` データクラスの挙動
    """

    def test_fields_are_stored_as_is(self):
        """
        全フィールドがそのまま格納される
        """
        ts = datetime(2026, 5, 3, 12, 30, 45, tzinfo=timezone.utc)
        rec = AnswerRecord(user_id=42, song_name="Aragami", correct=True, answered_at=ts)
        assert rec.user_id == 42
        assert rec.song_name == "Aragami"
        assert rec.correct is True
        assert rec.answered_at == ts


# ==================================================
# Session: 初期化
# ==================================================
class TestSessionInit:
    """
    `Session.__init__` / `__post_init__` の挙動
    """

    def test_defaults(self):
        """
        オプションフィールドのデフォルトが期待値で設定される
        """
        session = _make_session()
        assert session.rotate is False
        assert session.grayscale is False
        assert session.mosaic_block == 300
        assert session.play_records == []
        assert session.answer_records == []
        # ピン留めメッセージ ID は /start 完了後に書き込むため初期値は None
        assert session.pinned_message_id is None

    def test_pinned_message_id_can_be_assigned(self):
        """
        pinned_message_id は後から書き込んで `/play`・`/end` から参照できる
        """
        session = _make_session()
        session.pinned_message_id = 9876543210
        assert session.pinned_message_id == 9876543210

    def test_panel_count_must_match_tasks(self):
        """
        panel_count と tasks 数が不一致なら ValueError
        """
        with pytest.raises(ValueError, match="panel_count と tasks 数"):
            _make_session(panel_count=4, tasks=[_make_task() for _ in range(3)])

    def test_panel_count_zero_raises(self):
        """
        panel_count が 0 なら ValueError
        """
        with pytest.raises(ValueError, match="panel_count"):
            _make_session(panel_count=0, tasks=[])

    def test_mosaic_block_must_be_positive(self):
        """
        mosaic_block が 0 以下なら ValueError
        """
        with pytest.raises(ValueError, match="mosaic_block"):
            _make_session(mosaic_block=0)
        with pytest.raises(ValueError, match="mosaic_block"):
            _make_session(mosaic_block=-1)

    def test_play_and_answer_lists_are_independent_per_instance(self):
        """
        default_factory により、別インスタンスのリストは共有されない
        """
        s1 = _make_session()
        s2 = _make_session()
        s1.play_records.append(
            PlayRecord(song_name="X", difficulty="Hard", charming=1, combo=1)
        )
        assert len(s2.play_records) == 0


# ==================================================
# Session: 進捗参照
# ==================================================
class TestSessionProgress:
    """
    クリア状況参照メソッドの挙動
    """

    def test_cleared_panel_indices_empty_initially(self):
        """
        新規セッションではクリア済みパネルは無い
        """
        session = _make_session()
        assert session.cleared_panel_indices() == set()

    def test_cleared_panel_indices_reflects_task_state(self):
        """
        cleared = True のタスクの index 集合が返る
        """
        # 4 タスク中 index 0, 2 をクリア済みに
        tasks = [
            _make_task(set_value=1, current=1),  # cleared
            _make_task(),
            _make_task(set_value=1, current=1),  # cleared
            _make_task(),
        ]
        session = _make_session(panel_count=4, tasks=tasks)
        assert session.cleared_panel_indices() == {0, 2}

    def test_is_all_cleared_false_when_partial(self):
        """
        一部のみクリアなら is_all_cleared は False
        """
        tasks = [
            _make_task(set_value=1, current=1),
            _make_task(),
        ]
        session = _make_session(panel_count=2, tasks=tasks)
        assert session.is_all_cleared() is False

    def test_is_all_cleared_true_when_all_cleared(self):
        """
        全タスクが cleared なら True
        """
        tasks = [_make_task(set_value=1, current=1) for _ in range(4)]
        session = _make_session(panel_count=4, tasks=tasks)
        assert session.is_all_cleared() is True


# ==================================================
# Session: 履歴追加
# ==================================================
class TestSessionRecords:
    """
    `add_play` / `add_answer` の挙動
    """

    def test_add_play_appends_in_order(self):
        """
        add_play の呼び出し順に play_records が積まれる
        """
        session = _make_session()
        r1 = PlayRecord(song_name="A", difficulty="Hard", charming=100, combo=200)
        r2 = PlayRecord(song_name="B", difficulty="Extra", charming=120, combo=240)
        session.add_play(r1)
        session.add_play(r2)
        assert session.play_records == [r1, r2]

    def test_add_answer_appends_in_order(self):
        """
        add_answer の呼び出し順に answer_records が積まれる
        """
        session = _make_session()
        ts = datetime(2026, 5, 3, 10, 5, 0, tzinfo=timezone.utc)
        a1 = AnswerRecord(user_id=1, song_name="X", correct=False, answered_at=ts)
        a2 = AnswerRecord(user_id=2, song_name="Aragami", correct=True, answered_at=ts)
        session.add_answer(a1)
        session.add_answer(a2)
        assert session.answer_records == [a1, a2]
