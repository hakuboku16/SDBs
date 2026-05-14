"""
task_generator.py のユニットテスト

`TaskGenerator` の各サンプリング規則 (set / value: range / value: candidate /
特殊 candidate) と、エラー系の挙動を検証します。

実 JSON (assets/data/all_topics.json, all_songs.json) 利用と、
独自 JSON を組み立てて挙動を厳密に確認するパターンを併用します。
"""

import json
import random
from pathlib import Path

import pytest

from src.services.song_repository import SongRepository
from src.services.task import Task
from src.services.task_generator import TaskGenerator
from src.utils.helpers import get_absolute_path


# ==================================================
# fixtures
# ==================================================
@pytest.fixture
def real_topics_json() -> Path:
    """
    リポジトリ同梱の本物の all_topics.json
    """
    return get_absolute_path("assets/data/all_topics.json")


@pytest.fixture
def real_song_repo() -> SongRepository:
    """
    リポジトリ同梱の本物の all_songs.json を用いた SongRepository
    """
    return SongRepository(
        songs_json=get_absolute_path("assets/data/all_songs.json"),
        images_dir=get_absolute_path("assets/images"),
    )


@pytest.fixture
def fixed_rng() -> random.Random:
    """
    再現性のある乱数生成器 (seed 固定)
    """
    return random.Random(42)


@pytest.fixture
def real_generator(
    real_topics_json: Path,
    real_song_repo: SongRepository,
    fixed_rng: random.Random,
) -> TaskGenerator:
    """
    実 JSON ベースの TaskGenerator (seed 固定)
    """
    return TaskGenerator(
        topics_json=real_topics_json,
        song_repository=real_song_repo,
        rng=fixed_rng,
    )


@pytest.fixture
def fake_song_repo(tmp_path: Path) -> SongRepository:
    """
    特殊 candidate 解決の検証用に shelf / book / version の集合が分かる最小構成の SongRepository
    """
    data = {
        "ShelfA": {
            "BookX": {
                "Song1": {
                    "VERSION": "1.0",
                    "LEVEL": {"Easy": 1},
                    "NOTES": {"Easy": 100},
                    "TIME": 100,
                    "COMPOSER": ["C1"],
                },
                "Song2": {
                    "VERSION": "2.0",
                    "LEVEL": {"Easy": 1},
                    "NOTES": {"Easy": 100},
                    "TIME": 100,
                    "COMPOSER": ["C1"],
                },
            },
        },
        "ShelfB": {
            "BookY": {
                "Song3": {
                    "VERSION": "1.0",
                    "LEVEL": {"Easy": 1},
                    "NOTES": {"Easy": 100},
                    "TIME": 100,
                    "COMPOSER": ["C1"],
                },
            },
        },
    }
    songs_json = tmp_path / "songs.json"
    songs_json.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    images_dir = tmp_path / "images"
    images_dir.mkdir()

    return SongRepository(songs_json=songs_json, images_dir=images_dir)


def _write_topics(tmp_path: Path, topics: list[dict]) -> Path:
    """
    ヘルパー: 任意のお題定義をテンポラリの JSON に書き出してパスを返す

    description は Task 生成時に必須となったため、テストで明示指定が無い場合は
    placeholder を含むダミー文字列を補完する (description 自体の検証はしない)。
    """
    enriched = [
        {
            **t,
            "description": t.get(
                "description", "テスト用 description value をset回play"
            ),
        }
        for t in topics
    ]
    path = tmp_path / "topics.json"
    path.write_text(json.dumps(enriched, ensure_ascii=False), encoding="utf-8")
    return path


# ==================================================
# ロード
# ==================================================
class TestTaskGeneratorLoad:
    """
    `TaskGenerator.__init__` (JSON ロード) の挙動
    """

    def test_load_real_topics(self, real_generator: TaskGenerator):
        """
        実 JSON から 25 件のお題がロードされる (現時点のスナップショット)
        """
        assert real_generator.topic_count() == 25

    def test_load_missing_file_raises(
        self, tmp_path: Path, fake_song_repo: SongRepository
    ):
        """
        ファイル不在で FileNotFoundError
        """
        with pytest.raises(FileNotFoundError):
            TaskGenerator(
                topics_json=tmp_path / "missing.json",
                song_repository=fake_song_repo,
            )

    def test_load_non_list_raises(
        self, tmp_path: Path, fake_song_repo: SongRepository
    ):
        """
        トップレベルがリストでない JSON は ValueError
        """
        path = tmp_path / "topics.json"
        path.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
        with pytest.raises(ValueError, match="リスト"):
            TaskGenerator(topics_json=path, song_repository=fake_song_repo)


# ==================================================
# generate (公開 API)
# ==================================================
class TestTaskGeneratorGenerate:
    """
    `TaskGenerator.generate` の挙動
    """

    def test_generate_returns_requested_count(self, real_generator: TaskGenerator):
        """
        指定された数だけ Task が返る
        """
        tasks = real_generator.generate(panel_count=4)
        assert len(tasks) == 4
        assert all(isinstance(t, Task) for t in tasks)

    def test_generate_supports_all_panel_counts(
        self, real_generator: TaskGenerator
    ):
        """
        4 / 9 / 16 / 25 の全パネル数で生成できる (お題 25 種でちょうど)
        """
        for n in (4, 9, 16, 25):
            tasks = real_generator.generate(panel_count=n)
            assert len(tasks) == n

    def test_generate_no_duplicate_type(self, real_generator: TaskGenerator):
        """
        生成された Task の type は重複しない
        """
        tasks = real_generator.generate(panel_count=25)
        types = [t.type for t in tasks]
        assert len(types) == len(set(types))

    def test_generate_zero_raises(self, real_generator: TaskGenerator):
        """
        panel_count = 0 で ValueError
        """
        with pytest.raises(ValueError, match="panel_count"):
            real_generator.generate(panel_count=0)

    def test_generate_negative_raises(self, real_generator: TaskGenerator):
        """
        panel_count が負で ValueError
        """
        with pytest.raises(ValueError, match="panel_count"):
            real_generator.generate(panel_count=-1)

    def test_generate_exceeding_topic_count_raises(
        self, real_generator: TaskGenerator
    ):
        """
        panel_count がお題総数を超えると ValueError
        """
        n = real_generator.topic_count() + 1
        with pytest.raises(ValueError, match="お題マスター件数"):
            real_generator.generate(panel_count=n)

    def test_generate_set_value_within_spec_range(
        self, real_generator: TaskGenerator
    ):
        """
        生成された全タスクの set_value は、対応するお題の set 範囲内に収まる
        """
        # type → set 仕様の対応表を実 JSON から構築
        with open(get_absolute_path("assets/data/all_topics.json"), "r", encoding="utf-8") as f:
            spec_by_type = {t["type"]: t["set"] for t in json.load(f)}

        tasks = real_generator.generate(panel_count=25)
        for task in tasks:
            lo, hi, step = spec_by_type[task.type]
            allowed = set(range(lo, hi + 1, step))
            assert (
                task.set_value in allowed
            ), f"{task.type}: set_value={task.set_value} が {allowed} に含まれない"

    def test_generate_initial_progress_is_zero(
        self, real_generator: TaskGenerator
    ):
        """
        生成直後の Task は current=0, cleared=False
        """
        tasks = real_generator.generate(panel_count=9)
        assert all(t.current == 0 for t in tasks)
        assert all(t.cleared is False for t in tasks)


# ==================================================
# set_value サンプリング (private)
# ==================================================
class TestSampleSetValue:
    """
    `_sample_set_value` の挙動 (経路を制御するため独自 JSON を利用)
    """

    def test_single_value_range(
        self, tmp_path: Path, fake_song_repo: SongRepository
    ):
        """
        [N, N, 1] のような単一値レンジは必ずその値を返す
        """
        topics = [{"type": "level_total", "set": [5, 5, 1], "value": None}]
        gen = TaskGenerator(
            topics_json=_write_topics(tmp_path, topics),
            song_repository=fake_song_repo,
            rng=random.Random(0),
        )
        tasks = gen.generate(panel_count=1)
        assert tasks[0].set_value == 5

    def test_step_skips_intermediate_values(
        self, tmp_path: Path, fake_song_repo: SongRepository
    ):
        """
        step=1000 のように、列挙値以外は出ない (3000, 4000, 5000, 6000)
        """
        topics = [{"type": "result_charming_total", "set": [3000, 6000, 1000], "value": None}]
        path = _write_topics(tmp_path, topics)
        allowed = {3000, 4000, 5000, 6000}
        # 多数試行しても allowed の中に収まることを確認
        for seed in range(50):
            gen = TaskGenerator(
                topics_json=path,
                song_repository=fake_song_repo,
                rng=random.Random(seed),
            )
            assert gen.generate(panel_count=1)[0].set_value in allowed

    def test_invalid_set_length(
        self, tmp_path: Path, fake_song_repo: SongRepository
    ):
        """
        set の要素数が 3 でないと ValueError
        """
        topics = [{"type": "x", "set": [1, 2], "value": None}]
        gen = TaskGenerator(
            topics_json=_write_topics(tmp_path, topics),
            song_repository=fake_song_repo,
        )
        with pytest.raises(ValueError, match="set"):
            gen.generate(panel_count=1)

    def test_invalid_set_step_zero(
        self, tmp_path: Path, fake_song_repo: SongRepository
    ):
        """
        step=0 の set は ValueError
        """
        topics = [{"type": "x", "set": [1, 5, 0], "value": None}]
        gen = TaskGenerator(
            topics_json=_write_topics(tmp_path, topics),
            song_repository=fake_song_repo,
        )
        with pytest.raises(ValueError, match="step"):
            gen.generate(panel_count=1)


# ==================================================
# value: range サンプリング
# ==================================================
class TestSampleRange:
    """
    value: range のサンプリング挙動
    """

    def test_int_range_yields_int_within_range(
        self, tmp_path: Path, fake_song_repo: SongRepository
    ):
        """
        整数 range は整数値を返し、列挙範囲に含まれる
        """
        topics = [{"type": "level", "set": [1, 1, 1], "value": {"range": [1, 12, 1]}}]
        path = _write_topics(tmp_path, topics)
        allowed = set(range(1, 13))
        for seed in range(20):
            gen = TaskGenerator(
                topics_json=path,
                song_repository=fake_song_repo,
                rng=random.Random(seed),
            )
            value = gen.generate(panel_count=1)[0].value
            assert isinstance(value, int)
            assert value in allowed

    def test_int_range_with_step(
        self, tmp_path: Path, fake_song_repo: SongRepository
    ):
        """
        step > 1 の整数 range は飛び値のみを返す
        """
        topics = [{"type": "notes_above", "set": [1, 1, 1], "value": {"range": [1100, 1600, 100]}}]
        path = _write_topics(tmp_path, topics)
        allowed = {1100, 1200, 1300, 1400, 1500, 1600}
        for seed in range(50):
            gen = TaskGenerator(
                topics_json=path,
                song_repository=fake_song_repo,
                rng=random.Random(seed),
            )
            value = gen.generate(panel_count=1)[0].value
            assert value in allowed

    def test_float_range_yields_float_within_range(
        self, tmp_path: Path, fake_song_repo: SongRepository
    ):
        """
        float range は float 値を返し、列挙範囲に含まれる (0.8〜1.4 step 0.1)
        """
        topics = [
            {"type": "notes_density_below", "set": [1, 1, 1], "value": {"range": [0.8, 1.4, 0.1]}}
        ]
        path = _write_topics(tmp_path, topics)
        # 期待される列挙値 (10 桁丸めで等価比較)
        expected = [round(0.8 + i * 0.1, 10) for i in range(7)]
        for seed in range(30):
            gen = TaskGenerator(
                topics_json=path,
                song_repository=fake_song_repo,
                rng=random.Random(seed),
            )
            value = gen.generate(panel_count=1)[0].value
            assert isinstance(value, float)
            assert any(abs(value - e) < 1e-9 for e in expected)

    def test_invalid_range_step_negative(
        self, tmp_path: Path, fake_song_repo: SongRepository
    ):
        """
        range の step が負なら ValueError
        """
        topics = [{"type": "x", "set": [1, 1, 1], "value": {"range": [1, 5, -1]}}]
        gen = TaskGenerator(
            topics_json=_write_topics(tmp_path, topics),
            song_repository=fake_song_repo,
        )
        with pytest.raises(ValueError, match="step"):
            gen.generate(panel_count=1)


# ==================================================
# value: candidate サンプリング
# ==================================================
class TestSampleCandidate:
    """
    value: candidate のサンプリング挙動
    """

    def test_string_candidate_returns_list_of_chars(
        self, tmp_path: Path, fake_song_repo: SongRepository
    ):
        """
        文字列 candidate からは 1 文字単位で choice 個サンプリングされ、結果は list[str]
        """
        topics = [
            {
                "type": "title_include",
                "set": [1, 1, 1],
                "value": {"candidate": "abcde", "choice": 2},
            }
        ]
        path = _write_topics(tmp_path, topics)
        for seed in range(10):
            gen = TaskGenerator(
                topics_json=path,
                song_repository=fake_song_repo,
                rng=random.Random(seed),
            )
            value = gen.generate(panel_count=1)[0].value
            assert isinstance(value, list)
            assert len(value) == 2
            # 重複なし、母集団に含まれる
            assert len(set(value)) == 2
            assert all(c in "abcde" for c in value)

    def test_list_candidate(self, tmp_path: Path, fake_song_repo: SongRepository):
        """
        リスト candidate からは要素単位で choice 個サンプリングされる
        """
        topics = [
            {
                "type": "difficult",
                "set": [1, 1, 1],
                "value": {
                    "candidate": ["Easy", "Normal", "Hard"],
                    "choice": 1,
                },
            }
        ]
        path = _write_topics(tmp_path, topics)
        for seed in range(20):
            gen = TaskGenerator(
                topics_json=path,
                song_repository=fake_song_repo,
                rng=random.Random(seed),
            )
            value = gen.generate(panel_count=1)[0].value
            # choice=1 でも返り値は list (要素 1 個)
            assert isinstance(value, list)
            assert len(value) == 1
            assert value[0] in {"Easy", "Normal", "Hard"}

    def test_choice_exceeds_candidate_size(
        self, tmp_path: Path, fake_song_repo: SongRepository
    ):
        """
        choice が母集団サイズを超えると ValueError
        """
        topics = [
            {
                "type": "x",
                "set": [1, 1, 1],
                "value": {"candidate": "ab", "choice": 5},
            }
        ]
        gen = TaskGenerator(
            topics_json=_write_topics(tmp_path, topics),
            song_repository=fake_song_repo,
        )
        with pytest.raises(ValueError, match="母集団"):
            gen.generate(panel_count=1)

    def test_invalid_choice_zero(
        self, tmp_path: Path, fake_song_repo: SongRepository
    ):
        """
        choice = 0 は ValueError
        """
        topics = [
            {
                "type": "x",
                "set": [1, 1, 1],
                "value": {"candidate": "ab", "choice": 0},
            }
        ]
        gen = TaskGenerator(
            topics_json=_write_topics(tmp_path, topics),
            song_repository=fake_song_repo,
        )
        with pytest.raises(ValueError, match="choice"):
            gen.generate(panel_count=1)


# ==================================================
# 特殊 candidate (version_list / book_list / shelf_list)
# ==================================================
class TestSpecialCandidate:
    """
    SongRepository から動的に解決される特殊 candidate の挙動
    """

    def test_version_list_resolves_from_repo(
        self, tmp_path: Path, fake_song_repo: SongRepository
    ):
        """
        version_list は楽曲データの version 集合 ({"1.0", "2.0"}) から解決される
        """
        topics = [
            {
                "type": "version",
                "set": [1, 1, 1],
                "value": {"candidate": "version_list", "choice": 2},
            }
        ]
        path = _write_topics(tmp_path, topics)
        for seed in range(10):
            gen = TaskGenerator(
                topics_json=path,
                song_repository=fake_song_repo,
                rng=random.Random(seed),
            )
            value = gen.generate(panel_count=1)[0].value
            assert isinstance(value, list)
            assert set(value) == {"1.0", "2.0"}

    def test_book_list_resolves_from_repo(
        self, tmp_path: Path, fake_song_repo: SongRepository
    ):
        """
        book_list は楽曲データの book 集合 ({"BookX", "BookY"}) から解決される
        """
        topics = [
            {
                "type": "book",
                "set": [1, 1, 1],
                "value": {"candidate": "book_list", "choice": 1},
            }
        ]
        path = _write_topics(tmp_path, topics)
        for seed in range(10):
            gen = TaskGenerator(
                topics_json=path,
                song_repository=fake_song_repo,
                rng=random.Random(seed),
            )
            value = gen.generate(panel_count=1)[0].value
            assert isinstance(value, list)
            assert len(value) == 1
            assert value[0] in {"BookX", "BookY"}

    def test_shelf_list_resolves_from_repo(
        self, tmp_path: Path, fake_song_repo: SongRepository
    ):
        """
        shelf_list は楽曲データの shelf 集合 ({"ShelfA", "ShelfB"}) から解決される
        """
        topics = [
            {
                "type": "shelf",
                "set": [1, 1, 1],
                "value": {"candidate": "shelf_list", "choice": 1},
            }
        ]
        path = _write_topics(tmp_path, topics)
        for seed in range(10):
            gen = TaskGenerator(
                topics_json=path,
                song_repository=fake_song_repo,
                rng=random.Random(seed),
            )
            value = gen.generate(panel_count=1)[0].value
            assert value[0] in {"ShelfA", "ShelfB"}

    def test_real_special_candidates_use_real_song_data(
        self,
        real_topics_json: Path,
        real_song_repo: SongRepository,
    ):
        """
        実 JSON の特殊 candidate (version/book/shelf) も実楽曲データから解決される
        """
        gen = TaskGenerator(
            topics_json=real_topics_json,
            song_repository=real_song_repo,
            rng=random.Random(0),
        )
        # 実楽曲データの集合
        songs = real_song_repo.all()
        all_versions = {s.version for s in songs}
        all_books = {s.book for s in songs}
        all_shelves = {s.shelf for s in songs}

        # 全 type を含むよう 25 個生成
        tasks = gen.generate(panel_count=25)
        by_type = {t.type: t for t in tasks}

        version_task = by_type["version"]
        assert all(v in all_versions for v in version_task.value)

        book_task = by_type["book"]
        assert all(b in all_books for b in book_task.value)

        shelf_task = by_type["shelf"]
        assert all(s in all_shelves for s in shelf_task.value)


# ==================================================
# value: None
# ==================================================
class TestValueNone:
    """
    value: null 系お題 (level_total, result_*_total, composer_members, featuring) の挙動
    """

    def test_value_none_passes_through(
        self, tmp_path: Path, fake_song_repo: SongRepository
    ):
        """
        value: null のお題は Task.value = None で生成される
        """
        topics = [{"type": "level_total", "set": [30, 50, 10], "value": None}]
        gen = TaskGenerator(
            topics_json=_write_topics(tmp_path, topics),
            song_repository=fake_song_repo,
            rng=random.Random(0),
        )
        task = gen.generate(panel_count=1)[0]
        assert task.value is None


# ==================================================
# play_quality 抽選 / description_template 伝搬
# ==================================================
class TestPlayQualityAndDescription:
    """
    `_sample_play_quality` の重み付き抽選と、
    `description_template` が Task に正しく伝搬される挙動
    """

    def test_play_quality_is_one_of_three(
        self, tmp_path: Path, fake_song_repo: SongRepository
    ):
        """
        生成された Task の play_quality は AC / FC / プレイ のいずれか
        """
        topics = [{"type": "level_total", "set": [1, 1, 1], "value": None}]
        gen = TaskGenerator(
            topics_json=_write_topics(tmp_path, topics),
            song_repository=fake_song_repo,
            rng=random.Random(0),
        )
        task = gen.generate(panel_count=1)[0]
        assert task.play_quality in {"AC", "FC", "プレイ"}

    def test_play_quality_distribution_matches_weights(
        self, tmp_path: Path, fake_song_repo: SongRepository
    ):
        """
        十分な試行回数で AC:1 / FC:3 / プレイ:6 の比率に近づく
        (各カテゴリ ±2.5% 以内に収まることを確認)
        """
        topics = [{"type": "level_total", "set": [1, 1, 1], "value": None}]
        gen = TaskGenerator(
            topics_json=_write_topics(tmp_path, topics),
            song_repository=fake_song_repo,
            rng=random.Random(12345),
        )
        n = 10000
        counts = {"AC": 0, "FC": 0, "プレイ": 0}
        for _ in range(n):
            counts[gen._sample_play_quality()] += 1

        # 期待: AC=0.1, FC=0.3, プレイ=0.6
        assert abs(counts["AC"] / n - 0.1) < 0.025
        assert abs(counts["FC"] / n - 0.3) < 0.025
        assert abs(counts["プレイ"] / n - 0.6) < 0.025

    def test_description_template_is_propagated(
        self, tmp_path: Path, fake_song_repo: SongRepository
    ):
        """
        description フィールドはそのまま Task.description_template に伝搬される
        """
        topics = [
            {
                "type": "level_total",
                "set": [1, 1, 1],
                "value": None,
                "description": "playした譜面のレベルの合計がset",
            }
        ]
        gen = TaskGenerator(
            topics_json=_write_topics(tmp_path, topics),
            song_repository=fake_song_repo,
            rng=random.Random(0),
        )
        task = gen.generate(panel_count=1)[0]
        assert task.description_template == "playした譜面のレベルの合計がset"

    def test_missing_description_raises(
        self, tmp_path: Path, fake_song_repo: SongRepository
    ):
        """
        お題に description フィールドが無いと ValueError
        (`_write_topics` を経由せず生 JSON を書き出して検証)
        """
        path = tmp_path / "topics.json"
        topics = [{"type": "level_total", "set": [1, 1, 1], "value": None}]
        path.write_text(json.dumps(topics, ensure_ascii=False), encoding="utf-8")
        gen = TaskGenerator(
            topics_json=path,
            song_repository=fake_song_repo,
        )
        with pytest.raises(ValueError, match="description"):
            gen.generate(panel_count=1)


# ==================================================
# 再現性 (seed 固定)
# ==================================================
class TestReproducibility:
    """
    乱数生成器 (rng) を固定すれば結果が再現する
    """

    def test_same_seed_yields_same_tasks(
        self,
        real_topics_json: Path,
        real_song_repo: SongRepository,
    ):
        """
        同一 seed の Random を渡せば同じ Task 列が生成される
        """
        gen_a = TaskGenerator(
            topics_json=real_topics_json,
            song_repository=real_song_repo,
            rng=random.Random(123),
        )
        gen_b = TaskGenerator(
            topics_json=real_topics_json,
            song_repository=real_song_repo,
            rng=random.Random(123),
        )
        tasks_a = gen_a.generate(panel_count=9)
        tasks_b = gen_b.generate(panel_count=9)

        assert [t.type for t in tasks_a] == [t.type for t in tasks_b]
        assert [t.set_value for t in tasks_a] == [t.set_value for t in tasks_b]
        assert [t.value for t in tasks_a] == [t.value for t in tasks_b]
