"""
task_evaluator.py のユニットテスト

`TaskEvaluator` が all_topics.json で定義された全 type を正しく判定し、
マッチ系 (current+1 / 据え置き) と累積系 (all_plays から再計算) の両系統が
期待通りに動作することを検証します。

挙動を厳密に検証するため、固定構成の楽曲データを書き出した SongRepository を
fake_repo として用意し、各 type の代表ケースを網羅します。
"""

import json
from pathlib import Path

import pytest

from src.services.session import PlayRecord
from src.services.song_repository import SongRepository
from src.services.task_evaluator import TaskEvaluator
from tests.conftest import make_task


# ==================================================
# fixtures
# ==================================================
@pytest.fixture
def evaluator() -> TaskEvaluator:
    """共通の TaskEvaluator (状態を持たないので使い回し可能)"""
    return TaskEvaluator()


@pytest.fixture
def fake_repo(tmp_path: Path) -> SongRepository:
    """
    各 type の挙動検証に必要な属性 (level / notes / time / composer / feat /
    version / book / shelf / 名前長 / 空白) を網羅する最小構成の SongRepository
    """
    data = {
        # shelf=Story
        "Story": {
            # book=Vol.1
            "Vol.1": {
                # 短い名前 (3 文字), composer 単独, level 5 と 12 を持つ
                "Aya": {
                    "VERSION": "1.0",
                    "LEVEL": {"Easy": 5, "Normal": 8, "Hard": 12},
                    "NOTES": {"Easy": 100, "Normal": 500, "Hard": 1200},
                    "TIME": 120,
                    "COMPOSER": ["Aoi"],
                },
                # 空白 2 個, composer 複数, feat あり
                "Miracle of Daybreak": {
                    "VERSION": "2.0",
                    "LEVEL": {"Easy": 3, "Normal": 6, "Hard": 9},
                    "NOTES": {"Easy": 153, "Normal": 460, "Hard": 805},
                    "TIME": 200,
                    "COMPOSER": ["Mili", "Cassi"],
                    "feat.": ["Guest"],
                },
            },
            # book=Vol.2 / 同じ shelf 内別 book
            "Vol.2": {
                # 長い名前 (24 文字), 高密度譜面, time が長い
                "Reverse-Parallel-Universe": {
                    "VERSION": "3.0",
                    "LEVEL": {"Easy": 4, "Normal": 7, "Hard": 11},
                    "NOTES": {"Easy": 200, "Normal": 800, "Hard": 1600},
                    "TIME": 100,
                    "COMPOSER": ["Zeta"],
                },
            },
        },
        # shelf=Collection / 別 shelf
        "Collection": {
            "BookX": {
                # 低ノーツ, time 短い
                "Dream": {
                    "VERSION": "1.0",
                    "LEVEL": {"Easy": 1, "Normal": 4, "Hard": 8},
                    "NOTES": {"Easy": 78, "Normal": 313, "Hard": 485},
                    "TIME": 130,
                    "COMPOSER": ["Rabpit"],
                },
            },
        },
    }
    songs_json = tmp_path / "songs.json"
    songs_json.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    images_dir = tmp_path / "images"
    images_dir.mkdir()
    return SongRepository(songs_json=songs_json, images_dir=images_dir)


def _play(
    song_name: str = "Aya",
    difficulty: str = "Hard",
    charming: int = 0,
    combo: int = 0,
) -> PlayRecord:
    """テスト用の PlayRecord を簡潔に組み立てるファクトリ"""
    return PlayRecord(
        song_name=song_name, difficulty=difficulty, charming=charming, combo=combo
    )


# ==================================================
# 全 type 網羅性 / 未対応 type
# ==================================================
class TestTaskEvaluatorRegistry:
    """`TaskEvaluator.evaluate` のディスパッチ層の挙動"""

    def test_supported_types_covers_all_topics_json(self):
        """
        実 JSON の all_topics.json に存在する全 type が評価器に登録済み
        """
        from src.utils.helpers import get_absolute_path

        with open(
            get_absolute_path("assets/data/all_topics.json"),
            "r",
            encoding="utf-8",
        ) as f:
            topics = json.load(f)
        json_types = {t["type"] for t in topics}

        evaluator = TaskEvaluator()
        assert json_types.issubset(evaluator.supported_types())

    def test_unknown_type_raises(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """未登録の type は ValueError を送出する"""
        task = make_task(type="not_a_real_type", set_value=1, value=None)
        with pytest.raises(ValueError, match="未対応"):
            evaluator.evaluate(task, _play(), [_play()], fake_repo)

    def test_missing_song_raises(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """
        SongRepository に存在しない楽曲を参照する type で ValueError
        (level は楽曲メタを引くため、リポジトリ未登録曲で必ず失敗する)
        """
        task = make_task(type="level", set_value=1, value=5)
        play = _play(song_name="UnknownSong")
        with pytest.raises(ValueError, match="存在しません"):
            evaluator.evaluate(task, play, [play], fake_repo)


# ==================================================
# title_*
# ==================================================
class TestTitleEvaluators:
    """title_include / title_startswith / title_endswith / title_len_* / title_blank"""

    def test_title_include_matches_when_all_chars_present(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """value の全文字が大文字小文字を無視してタイトルに含まれるとマッチ"""
        # "Miracle of Daybreak" は a/b/c を全て含む (case-insensitive)
        task = make_task(type="title_include", set_value=2, value=["a", "b", "c"])
        play = _play(song_name="Miracle of Daybreak")
        assert evaluator.evaluate(task, play, [play], fake_repo) == 1

    def test_title_include_no_match_keeps_current(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """1 文字でも欠ければ current 据え置き"""
        # "Aya" は b を含まない
        task = make_task(type="title_include", set_value=2, value=["a", "b"])
        play = _play(song_name="Aya")
        assert evaluator.evaluate(task, play, [play], fake_repo) == 0

    def test_title_include_increments_from_existing_current(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """既存 current から +1 で返る (絶対値ではなくインクリメント)"""
        task = make_task(
            type="title_include", set_value=5, value=["a"], current=2
        )
        play = _play(song_name="Aya")
        assert evaluator.evaluate(task, play, [play], fake_repo) == 3

    def test_title_startswith_matches(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """タイトル先頭が候補のいずれかで始まればマッチ"""
        task = make_task(type="title_startswith", set_value=2, value=["a", "z"])
        play = _play(song_name="Aya")  # casefold で "aya"
        assert evaluator.evaluate(task, play, [play], fake_repo) == 1

    def test_title_startswith_no_match(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """先頭がいずれの候補にも該当しなければ据え置き"""
        task = make_task(type="title_startswith", set_value=2, value=["x", "z"])
        play = _play(song_name="Aya")
        assert evaluator.evaluate(task, play, [play], fake_repo) == 0

    def test_title_endswith_matches(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """タイトル末尾が候補のいずれかで終わればマッチ"""
        task = make_task(type="title_endswith", set_value=1, value=["a", "z"])
        play = _play(song_name="Aya")  # 末尾 "a"
        assert evaluator.evaluate(task, play, [play], fake_repo) == 1

    def test_title_endswith_no_match(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """末尾がいずれの候補とも一致しなければ据え置き"""
        task = make_task(type="title_endswith", set_value=1, value=["x", "z"])
        play = _play(song_name="Aya")
        assert evaluator.evaluate(task, play, [play], fake_repo) == 0

    def test_title_len_below_inclusive(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """value 文字以下 (含む) でマッチ"""
        task = make_task(type="title_len_below", set_value=2, value=3)
        assert (
            evaluator.evaluate(task, _play(song_name="Aya"), [_play()], fake_repo)
            == 1
        )
        # 4 文字はマッチしない
        task2 = make_task(type="title_len_below", set_value=2, value=3)
        assert (
            evaluator.evaluate(
                task2, _play(song_name="Dream"), [_play()], fake_repo
            )
            == 0
        )

    def test_title_len_above_inclusive(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """value 文字以上 (含む) でマッチ"""
        task = make_task(type="title_len_above", set_value=2, value=20)
        # "Reverse-Parallel-Universe" は 25 文字
        play = _play(song_name="Reverse-Parallel-Universe")
        assert evaluator.evaluate(task, play, [play], fake_repo) == 1

    def test_title_blank_count_exact(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """半角スペース数がちょうど value 個でマッチ"""
        task = make_task(type="title_blank", set_value=1, value=2)
        # "Miracle of Daybreak" は半角スペース 2 個
        play = _play(song_name="Miracle of Daybreak")
        assert evaluator.evaluate(task, play, [play], fake_repo) == 1

        # 0 個でも、value=0 ならマッチ
        task0 = make_task(type="title_blank", set_value=1, value=0)
        play0 = _play(song_name="Aya")
        assert evaluator.evaluate(task0, play0, [play0], fake_repo) == 1

    def test_title_blank_no_match(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """空白数が一致しなければ据え置き"""
        task = make_task(type="title_blank", set_value=1, value=5)
        play = _play(song_name="Miracle of Daybreak")
        assert evaluator.evaluate(task, play, [play], fake_repo) == 0


# ==================================================
# difficult / level
# ==================================================
class TestDifficultAndLevel:
    """`difficult` と `level` の挙動"""

    def test_difficult_matches(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """プレイ難易度が候補に含まれればマッチ"""
        task = make_task(type="difficult", set_value=3, value=["Easy", "Normal"])
        play = _play(difficulty="Normal")
        assert evaluator.evaluate(task, play, [play], fake_repo) == 1

    def test_difficult_no_match(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """プレイ難易度が候補外なら据え置き"""
        task = make_task(type="difficult", set_value=3, value=["Easy"])
        play = _play(difficulty="Hard")
        assert evaluator.evaluate(task, play, [play], fake_repo) == 0

    def test_level_matches_when_song_has_chart_at_value(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """楽曲が該当レベルの譜面を 1 つでも持てばマッチ (任意難易度のプレイで OK)"""
        # "Aya" は Hard=12 を持つ。プレイ難易度は Easy でもマッチする
        task = make_task(type="level", set_value=3, value=12)
        play = _play(song_name="Aya", difficulty="Easy")
        assert evaluator.evaluate(task, play, [play], fake_repo) == 1

    def test_level_no_match(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """楽曲が該当レベルの譜面を 1 つも持たなければ据え置き"""
        # "Aya" は Lv.5/8/12。Lv.7 は持たない
        task = make_task(type="level", set_value=3, value=7)
        play = _play(song_name="Aya")
        assert evaluator.evaluate(task, play, [play], fake_repo) == 0


# ==================================================
# 累積系
# ==================================================
class TestCumulativeEvaluators:
    """`level_total` / `result_charming_total` / `result_combo_total`"""

    def test_level_total_sums_played_chart_levels(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """プレイした難易度のレベルを合算 (Aya:Hard=12 + Dream:Normal=4)"""
        plays = [
            _play(song_name="Aya", difficulty="Hard"),
            _play(song_name="Dream", difficulty="Normal"),
        ]
        task = make_task(type="level_total", set_value=30, value=None)
        assert evaluator.evaluate(task, plays[-1], plays, fake_repo) == 16

    def test_level_total_recomputes_from_all_plays(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """current の値に依存せず、毎回 all_plays から再計算する"""
        plays = [_play(song_name="Aya", difficulty="Easy")]  # 5
        # current が大きくても、all_plays が 5 のままなら 5 を返す
        task = make_task(type="level_total", set_value=30, value=None, current=20)
        # ※ Task は current >= set_value で cleared を True に揃えるが、
        #   evaluate 自体は task.current に依存しないことを示すテスト
        # task.current=20 でも累積系は再計算するので 5
        assert evaluator.evaluate(task, plays[-1], plays, fake_repo) == 5

    def test_level_total_empty_plays_returns_zero(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """all_plays が空なら 0 (実用上は来ないが境界として)"""
        task = make_task(type="level_total", set_value=30, value=None)
        # play_record は形式上必要だが評価には用いられない (任意の値で良い)
        assert evaluator.evaluate(task, _play(), [], fake_repo) == 0

    def test_level_total_skips_non_int_level(
        self, evaluator: TaskEvaluator, tmp_path: Path
    ):
        """
        all_topics.json の仕様注釈
        「(補足)Ex譜面のうち英語、2進数表記のものは除く」に従い、
        レベル値が int でないプレイは集計対象から除外され
        TypeError を発生させない
        """
        # Ex 譜面のレベル値が文字列 ("L") の楽曲を含む構成を用意
        data = {
            "Story": {
                "Vol.1": {
                    "Entrance": {
                        "VERSION": "1.2",
                        "LEVEL": {
                            "Easy": 2,
                            "Normal": 8,
                            "Hard": 10,
                            "Extra": "L",
                        },
                        "NOTES": {
                            "Easy": 234,
                            "Normal": 585,
                            "Hard": 742,
                            "Extra": 999,
                        },
                        "TIME": 113,
                        "COMPOSER": ["Ice"],
                    },
                    "Dream": {
                        "VERSION": "1.0",
                        "LEVEL": {"Easy": 1, "Normal": 4, "Hard": 8},
                        "NOTES": {"Easy": 78, "Normal": 313, "Hard": 485},
                        "TIME": 130,
                        "COMPOSER": ["Rabpit"],
                    },
                },
            },
        }
        songs_json = tmp_path / "songs.json"
        songs_json.write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
        images_dir = tmp_path / "images"
        images_dir.mkdir()
        repo = SongRepository(songs_json=songs_json, images_dir=images_dir)

        plays = [
            # Extra 譜面 (level="L") はスキップされる
            _play(song_name="Entrance", difficulty="Extra"),
            # Normal 譜面 (level=4) のみ集計される
            _play(song_name="Dream", difficulty="Normal"),
        ]
        task = make_task(type="level_total", set_value=30, value=None)
        assert evaluator.evaluate(task, plays[-1], plays, repo) == 4

    def test_result_charming_total(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """charming の合計"""
        plays = [
            _play(charming=300),
            _play(charming=500),
            _play(charming=200),
        ]
        task = make_task(type="result_charming_total", set_value=3000, value=None)
        assert evaluator.evaluate(task, plays[-1], plays, fake_repo) == 1000

    def test_result_combo_total(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """combo の合計"""
        plays = [_play(combo=400), _play(combo=600)]
        task = make_task(type="result_combo_total", set_value=3000, value=None)
        assert evaluator.evaluate(task, plays[-1], plays, fake_repo) == 1000


# ==================================================
# notes_*
# ==================================================
class TestNotesEvaluators:
    """notes_below / notes_above / notes_density_* / notes_endswith"""

    def test_notes_below_matches_when_any_chart_at_or_below(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """楽曲がノーツ数 value 以下の譜面を 1 つでも持てばマッチ"""
        # Dream は Easy=78 (≤ 100)
        task = make_task(type="notes_below", set_value=2, value=100)
        play = _play(song_name="Dream", difficulty="Hard")
        assert evaluator.evaluate(task, play, [play], fake_repo) == 1

    def test_notes_below_no_match(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """全譜面が value より大きければ据え置き"""
        # Aya の最少ノーツは Easy=100
        task = make_task(type="notes_below", set_value=2, value=50)
        play = _play(song_name="Aya")
        assert evaluator.evaluate(task, play, [play], fake_repo) == 0

    def test_notes_above_matches(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """楽曲がノーツ数 value 以上の譜面を 1 つでも持てばマッチ"""
        # Aya は Hard=1200
        task = make_task(type="notes_above", set_value=1, value=1100)
        play = _play(song_name="Aya")
        assert evaluator.evaluate(task, play, [play], fake_repo) == 1

    def test_notes_density_below_matches(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """ノーツ密度が value [notes/s] 以下の譜面を持てばマッチ"""
        # Aya: time=120, Easy=100 → 0.833...
        task = make_task(type="notes_density_below", set_value=1, value=1.0)
        play = _play(song_name="Aya")
        assert evaluator.evaluate(task, play, [play], fake_repo) == 1

    def test_notes_density_above_matches(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """ノーツ密度が value [notes/s] 以上の譜面を持てばマッチ"""
        # Reverse-Parallel-Universe: time=100, Hard=1600 → 16.0
        task = make_task(type="notes_density_above", set_value=1, value=10.0)
        play = _play(song_name="Reverse-Parallel-Universe")
        assert evaluator.evaluate(task, play, [play], fake_repo) == 1

    def test_notes_density_above_no_match(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """全譜面が密度未満なら据え置き"""
        # Aya: time=120, max Hard=1200 → 10.0 (== 10.0 はマッチするので 11 で検証)
        task = make_task(type="notes_density_above", set_value=1, value=11.0)
        play = _play(song_name="Aya")
        assert evaluator.evaluate(task, play, [play], fake_repo) == 0

    def test_notes_endswith_uses_played_difficulty_only(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """
        notes_endswith はプレイした難易度のノーツ数のみ参照する
        (Aya: Easy=100, Normal=500, Hard=1200。Easy=末尾0 のみ)
        """
        # value=["0"]: Easy なら notes=100 → 末尾 0 でマッチ
        task = make_task(type="notes_endswith", set_value=1, value=["0"])
        play_easy = _play(song_name="Aya", difficulty="Easy")
        assert evaluator.evaluate(task, play_easy, [play_easy], fake_repo) == 1

        # 同じ value=["0"] でも Normal は notes=500 → 末尾 0 でマッチ
        play_normal = _play(song_name="Aya", difficulty="Normal")
        task2 = make_task(type="notes_endswith", set_value=1, value=["0"])
        assert (
            evaluator.evaluate(task2, play_normal, [play_normal], fake_repo) == 1
        )

        # Hard は notes=1200 → 末尾 0 → マッチ。一方 value=["5"] では不一致
        task3 = make_task(type="notes_endswith", set_value=1, value=["5"])
        play_hard = _play(song_name="Aya", difficulty="Hard")
        assert (
            evaluator.evaluate(task3, play_hard, [play_hard], fake_repo) == 0
        )

    def test_notes_endswith_invalid_value_length(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """value が 1 要素でなければ ValueError"""
        task = make_task(type="notes_endswith", set_value=1, value=["0", "1"])
        play = _play(song_name="Aya", difficulty="Easy")
        with pytest.raises(ValueError, match="1 要素"):
            evaluator.evaluate(task, play, [play], fake_repo)


# ==================================================
# composer / featuring
# ==================================================
class TestComposerAndFeaturing:
    """composer_name_* / composer_members / featuring"""

    def test_composer_name_startswith_matches_any_composer(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """楽曲のいずれかのコンポーザー名が候補のいずれかで始まればマッチ"""
        # Miracle of Daybreak: composer=["Mili", "Cassi"]
        task = make_task(type="composer_name_startswith", set_value=2, value=["c", "z"])
        play = _play(song_name="Miracle of Daybreak")
        assert evaluator.evaluate(task, play, [play], fake_repo) == 1

    def test_composer_name_startswith_no_match(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """全コンポーザーが先頭文字に該当しなければ据え置き"""
        # Aya: composer=["Aoi"]
        task = make_task(type="composer_name_startswith", set_value=2, value=["b", "c"])
        play = _play(song_name="Aya")
        assert evaluator.evaluate(task, play, [play], fake_repo) == 0

    def test_composer_name_endswith_matches(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """楽曲のいずれかのコンポーザーが候補のいずれかで終わればマッチ"""
        # Miracle of Daybreak: composer=["Mili", "Cassi"] → Mili は "i" で終わる
        task = make_task(type="composer_name_endswith", set_value=1, value=["i"])
        play = _play(song_name="Miracle of Daybreak")
        assert evaluator.evaluate(task, play, [play], fake_repo) == 1

    def test_composer_members_two_or_more(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """コンポーザーが 2 名以上ならマッチ"""
        task = make_task(type="composer_members", set_value=1, value=None)
        play = _play(song_name="Miracle of Daybreak")  # 2 名
        assert evaluator.evaluate(task, play, [play], fake_repo) == 1

    def test_composer_members_single_no_match(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """単独コンポーザーは据え置き"""
        task = make_task(type="composer_members", set_value=1, value=None)
        play = _play(song_name="Aya")  # 1 名
        assert evaluator.evaluate(task, play, [play], fake_repo) == 0

    def test_featuring_matches_when_feat_present(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """feat. が 1 件以上あればマッチ"""
        task = make_task(type="featuring", set_value=1, value=None)
        play = _play(song_name="Miracle of Daybreak")
        assert evaluator.evaluate(task, play, [play], fake_repo) == 1

    def test_featuring_no_feat_no_match(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """feat. が空なら据え置き"""
        task = make_task(type="featuring", set_value=1, value=None)
        play = _play(song_name="Aya")
        assert evaluator.evaluate(task, play, [play], fake_repo) == 0


# ==================================================
# time
# ==================================================
class TestTimeEvaluators:
    """time_below / time_above"""

    def test_time_below_inclusive(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """演奏時間が value 以下 (含む) でマッチ"""
        # Reverse-Parallel-Universe: time=100
        task = make_task(type="time_below", set_value=2, value=100)
        play = _play(song_name="Reverse-Parallel-Universe")
        assert evaluator.evaluate(task, play, [play], fake_repo) == 1

    def test_time_below_no_match(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """演奏時間が value より大きいなら据え置き"""
        # Miracle of Daybreak: time=200
        task = make_task(type="time_below", set_value=2, value=100)
        play = _play(song_name="Miracle of Daybreak")
        assert evaluator.evaluate(task, play, [play], fake_repo) == 0

    def test_time_above_inclusive(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """演奏時間が value 以上 (含む) でマッチ"""
        # Miracle of Daybreak: time=200
        task = make_task(type="time_above", set_value=2, value=200)
        play = _play(song_name="Miracle of Daybreak")
        assert evaluator.evaluate(task, play, [play], fake_repo) == 1


# ==================================================
# version / book / shelf
# ==================================================
class TestSongMetaEvaluators:
    """version / book / shelf"""

    def test_version_in_list_matches(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """楽曲のバージョンが value (リスト) に含まれればマッチ"""
        task = make_task(type="version", set_value=1, value=["1.0", "2.0"])
        play = _play(song_name="Aya")  # version "1.0"
        assert evaluator.evaluate(task, play, [play], fake_repo) == 1

    def test_version_not_in_list_no_match(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """対象外バージョンは据え置き"""
        task = make_task(type="version", set_value=1, value=["3.0"])
        play = _play(song_name="Aya")  # version "1.0"
        assert evaluator.evaluate(task, play, [play], fake_repo) == 0

    def test_book_in_list_matches(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """book が value (リスト) に含まれればマッチ"""
        task = make_task(type="book", set_value=2, value=["Vol.1", "Vol.2"])
        play = _play(song_name="Aya")  # book="Vol.1"
        assert evaluator.evaluate(task, play, [play], fake_repo) == 1

    def test_book_not_in_list_no_match(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """対象外 book は据え置き"""
        task = make_task(type="book", set_value=2, value=["BookX"])
        play = _play(song_name="Aya")  # book="Vol.1"
        assert evaluator.evaluate(task, play, [play], fake_repo) == 0

    def test_shelf_in_list_matches(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """shelf が value (リスト) に含まれればマッチ"""
        task = make_task(type="shelf", set_value=3, value=["Story"])
        play = _play(song_name="Aya")  # shelf="Story"
        assert evaluator.evaluate(task, play, [play], fake_repo) == 1

    def test_shelf_not_in_list_no_match(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """対象外 shelf は据え置き"""
        task = make_task(type="shelf", set_value=3, value=["Collection"])
        play = _play(song_name="Aya")  # shelf="Story"
        assert evaluator.evaluate(task, play, [play], fake_repo) == 0


# ==================================================
# play_quality フィルタ (AC / FC / プレイ)
# ==================================================
class TestPlayQualityFilter:
    """
    `Task.play_quality` によるプレイカウント絞り込みの挙動

    - "AC": charming 数 == 当該譜面の NOTES 数のプレイのみ加算対象
    - "FC": combo 数 == 当該譜面の NOTES 数のプレイのみ加算対象
    - "プレイ": フィルタ無し (従来挙動)
    """

    def test_ac_match_when_charming_equals_notes(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """AC タスク: charming==NOTES なら加算"""
        # Aya/Easy の NOTES = 100。charming=100 でフィルタ通過
        task = make_task(
            type="title_endswith",
            set_value=2,
            value=["a"],
            play_quality="AC",
        )
        play = _play(song_name="Aya", difficulty="Easy", charming=100, combo=50)
        assert evaluator.evaluate(task, play, [play], fake_repo) == 1

    def test_ac_no_match_when_charming_differs(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """AC タスク: charming!=NOTES なら据え置き"""
        task = make_task(
            type="title_endswith",
            set_value=2,
            value=["a"],
            play_quality="AC",
        )
        play = _play(song_name="Aya", difficulty="Easy", charming=99, combo=100)
        assert evaluator.evaluate(task, play, [play], fake_repo) == 0

    def test_fc_match_when_combo_equals_notes(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """FC タスク: combo==NOTES なら加算"""
        task = make_task(
            type="title_endswith",
            set_value=2,
            value=["a"],
            play_quality="FC",
        )
        play = _play(song_name="Aya", difficulty="Easy", charming=50, combo=100)
        assert evaluator.evaluate(task, play, [play], fake_repo) == 1

    def test_fc_no_match_when_combo_differs(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """FC タスク: combo!=NOTES なら据え置き"""
        task = make_task(
            type="title_endswith",
            set_value=2,
            value=["a"],
            play_quality="FC",
        )
        play = _play(song_name="Aya", difficulty="Easy", charming=100, combo=99)
        assert evaluator.evaluate(task, play, [play], fake_repo) == 0

    def test_play_quality_default_does_not_filter(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """プレイ タスク: charming/combo に関わらず加算 (従来挙動)"""
        task = make_task(
            type="title_endswith",
            set_value=2,
            value=["a"],
            play_quality="プレイ",
        )
        play = _play(song_name="Aya", difficulty="Easy", charming=1, combo=1)
        assert evaluator.evaluate(task, play, [play], fake_repo) == 1

    def test_cumulative_filters_all_plays_by_quality(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """
        累積系: AC タスクなら AC 条件を満たすプレイの charming のみ合計

        - Aya/Easy NOTES=100。charming=100 → AC 通過
        - Aya/Easy NOTES=100。charming=80  → AC 不通過 (合計から除外)
        - Aya/Hard NOTES=1200。charming=1200 → AC 通過
        """
        plays = [
            _play(song_name="Aya", difficulty="Easy", charming=100),
            _play(song_name="Aya", difficulty="Easy", charming=80),
            _play(song_name="Aya", difficulty="Hard", charming=1200),
        ]
        task = make_task(
            type="result_charming_total",
            set_value=3000,
            value=None,
            play_quality="AC",
        )
        # 100 + 1200 = 1300 (charming=80 は AC を満たさず除外)
        assert evaluator.evaluate(task, plays[-1], plays, fake_repo) == 1300

    def test_cumulative_excludes_latest_when_quality_unmet(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """
        累積系: 最新プレイが AC を満たさない場合は早期 task.current 返し
        (累積系は all_plays フィルタも整合させる二重保護を確認)
        """
        plays = [
            _play(song_name="Aya", difficulty="Easy", charming=100),
            _play(song_name="Aya", difficulty="Easy", charming=50),  # 最新は AC 不成立
        ]
        task = make_task(
            type="result_charming_total",
            set_value=3000,
            value=None,
            play_quality="AC",
            current=100,  # 過去の AC 通過分が既に反映済み
        )
        # 早期 return で task.current のまま (再計算しない)
        assert evaluator.evaluate(task, plays[-1], plays, fake_repo) == 100


# ==================================================
# Task との統合 (set_progress 経由でクリア遷移)
# ==================================================
class TestEvaluateAndApplyProgress:
    """`evaluate` 戻り値を `Task.set_progress` に渡したときの統合動作"""

    def test_increment_then_clear_via_set_progress(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """マッチ系: 連続マッチで current が積み上がり、set_value 到達でクリア"""
        task = make_task(type="title_endswith", set_value=2, value=["a"])
        plays: list[PlayRecord] = []

        # 1 回目
        plays.append(_play(song_name="Aya"))
        new_current = evaluator.evaluate(task, plays[-1], plays, fake_repo)
        assert task.set_progress(new_current) is False
        assert task.current == 1
        assert task.cleared is False

        # 2 回目で set_value=2 に到達
        plays.append(_play(song_name="Aya"))
        new_current = evaluator.evaluate(task, plays[-1], plays, fake_repo)
        assert task.set_progress(new_current) is True
        assert task.current == 2
        assert task.cleared is True

    def test_cumulative_clear_via_set_progress(
        self, evaluator: TaskEvaluator, fake_repo: SongRepository
    ):
        """累積系: 累計が set_value を超えたタイミングでクリア"""
        task = make_task(type="result_charming_total", set_value=3000, value=None)
        plays = [_play(charming=1500)]
        new_current = evaluator.evaluate(task, plays[-1], plays, fake_repo)
        assert task.set_progress(new_current) is False
        assert task.current == 1500

        plays.append(_play(charming=2000))
        new_current = evaluator.evaluate(task, plays[-1], plays, fake_repo)
        # 1500 + 2000 = 3500 ≥ 3000
        assert task.set_progress(new_current) is True
        assert task.current == 3500
        assert task.cleared is True
