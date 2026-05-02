"""
タスク (お題) のランダム生成を担うモジュール

`assets/data/all_topics.json` をマスターデータとして読み込み、
パネル数に応じた N 個の `Task` を組み立てます。

各お題マスターは以下の構造を持ちます。

- ``type`` (str): お題種別 (例: "title_include")
- ``set`` (list[int]): ``[min, max, step]``。``Task.set_value`` をこの範囲から 1 個ランダム抽出
- ``value`` (Any): お題ごとに固有のパラメータ (詳細は ``_sample_value`` 参照)

特殊な candidate 識別子 ``version_list`` / ``book_list`` / ``shelf_list`` は、
楽曲データから動的に集合を解決するため `SongRepository` を必要とします。
"""

import json
import random
from pathlib import Path
from typing import Any, Optional

from src.services.song_repository import SongRepository
from src.services.task import Task


# ==================================================
# タスクジェネレータ
# ==================================================
class TaskGenerator:
    """
    お題マスターから N 個の `Task` をランダム生成するジェネレータ

    type の重複は許可しません (お題マスターは 25 種類定義されており、
    最大パネル数 25 と一致するため、重複なしで全パネル数を充足できます)。
    """

    # candidate フィールドに記載される特殊識別子 (楽曲データから動的解決)
    _SPECIAL_CANDIDATES: tuple[str, ...] = (
        "version_list",
        "book_list",
        "shelf_list",
    )

    def __init__(
        self,
        topics_json: Path,
        song_repository: SongRepository,
        rng: Optional[random.Random] = None,
    ) -> None:
        """
        ジェネレータを初期化し、お題マスターをロードする

        Args:
            topics_json: お題マスター JSON ファイルへのパス
            song_repository: 特殊 candidate (version_list 等) の解決に用いる楽曲リポジトリ
            rng: 乱数生成器 (省略時は ``random.Random()``)。テスト時に固定 seed を渡せます

        Raises:
            FileNotFoundError: topics_json が存在しない場合
            ValueError: JSON のトップレベルがリストでない場合
        """
        self._topics: list[dict[str, Any]] = self._load(topics_json)
        self._song_repo: SongRepository = song_repository
        self._rng: random.Random = rng if rng is not None else random.Random()

    # --------------------------------------------------
    # ロード
    # --------------------------------------------------
    @staticmethod
    def _load(topics_json: Path) -> list[dict[str, Any]]:
        """
        お題マスター JSON を読み込む

        Raises:
            FileNotFoundError: ファイルが存在しない場合
            ValueError: トップレベル要素がリストでない場合
        """
        if not topics_json.is_file():
            raise FileNotFoundError(f"お題データが見つかりません: {topics_json}")

        with open(topics_json, "r", encoding="utf-8") as f:
            data: Any = json.load(f)

        if not isinstance(data, list):
            raise ValueError(
                "お題データのトップレベルはリスト形式である必要があります"
            )
        return data

    # --------------------------------------------------
    # 公開 API
    # --------------------------------------------------
    def topic_count(self) -> int:
        """
        ロード済みのお題マスター件数を返す
        """
        return len(self._topics)

    def generate(self, panel_count: int) -> list[Task]:
        """
        N 個の `Task` をランダム生成する

        type の重複は許可しません。``panel_count`` がお題マスター件数を超える場合は
        ``ValueError`` を送出します。

        Args:
            panel_count: 生成するタスク数 (1 以上、お題マスター件数以下)

        Returns:
            生成された `Task` のリスト

        Raises:
            ValueError: panel_count が範囲外、または各サンプリング規則に違反した場合
        """
        if panel_count < 1:
            raise ValueError(
                f"panel_count は 1 以上である必要があります: {panel_count}"
            )
        if panel_count > len(self._topics):
            raise ValueError(
                f"panel_count ({panel_count}) がお題マスター件数 "
                f"({len(self._topics)}) を超えています"
            )

        chosen: list[dict[str, Any]] = self._rng.sample(self._topics, k=panel_count)
        return [self._build_task(topic) for topic in chosen]

    # --------------------------------------------------
    # タスク組み立て
    # --------------------------------------------------
    def _build_task(self, topic: dict[str, Any]) -> Task:
        """
        単一のお題マスターから `Task` を組み立てる
        """
        if "type" not in topic:
            raise ValueError(f"お題に type フィールドがありません: {topic}")
        if "set" not in topic:
            raise ValueError(f"お題 '{topic['type']}' に set フィールドがありません")

        return Task(
            type=str(topic["type"]),
            set_value=self._sample_set_value(topic["set"]),
            value=self._sample_value(topic.get("value")),
        )

    # --------------------------------------------------
    # set_value サンプリング
    # --------------------------------------------------
    def _sample_set_value(self, set_spec: Any) -> int:
        """
        ``[min, max, step]`` から ``set_value`` を 1 個サンプリングする

        set_value は常に整数を想定します。

        Raises:
            ValueError: 仕様が想定外、または列挙範囲が空の場合
        """
        if not isinstance(set_spec, list) or len(set_spec) != 3:
            raise ValueError(
                f"set は [min, max, step] の 3 要素リストである必要があります: {set_spec}"
            )

        lo, hi, step = set_spec
        if not (
            isinstance(lo, int) and isinstance(hi, int) and isinstance(step, int)
        ):
            raise ValueError(f"set の各要素は整数である必要があります: {set_spec}")
        if step <= 0:
            raise ValueError(f"set の step は正の整数である必要があります: {step}")

        candidates: list[int] = list(range(lo, hi + 1, step))
        if not candidates:
            raise ValueError(f"set の列挙範囲が空です: {set_spec}")
        return self._rng.choice(candidates)

    # --------------------------------------------------
    # value サンプリング
    # --------------------------------------------------
    def _sample_value(self, value_spec: Any) -> Any:
        """
        value 仕様に従って ``Task.value`` に格納する値をサンプリングする

        対応する仕様:
            - None: そのまま None
            - ``{"range": [min, max, step]}``: 1 個ランダム抽出 (int / float 両対応)
            - ``{"candidate": <文字列 or リスト or 特殊識別子>, "choice": N}``:
              候補から N 個ランダム抽出 (重複なし)。返り値は常に list

        Raises:
            ValueError: 仕様が想定外の場合
        """
        if value_spec is None:
            return None

        if not isinstance(value_spec, dict):
            raise ValueError(f"value は null か dict である必要があります: {value_spec}")

        if "range" in value_spec:
            return self._sample_range(value_spec["range"])
        if "candidate" in value_spec:
            return self._sample_candidate(value_spec)
        raise ValueError(f"未知の value 仕様 (range/candidate なし): {value_spec}")

    def _sample_range(self, range_spec: Any) -> Any:
        """
        ``[min, max, step]`` から 1 個サンプリングする (int / float 両対応)

        step が浮動小数の場合は浮動小数誤差を抑えるため列挙時に丸めます。

        Raises:
            ValueError: 仕様が想定外、または列挙範囲が空の場合
        """
        if not isinstance(range_spec, list) or len(range_spec) != 3:
            raise ValueError(
                f"range は [min, max, step] の 3 要素リストである必要があります: {range_spec}"
            )

        lo, hi, step = range_spec
        if not all(isinstance(x, (int, float)) for x in (lo, hi, step)):
            raise ValueError(f"range の各要素は数値である必要があります: {range_spec}")
        if step <= 0:
            raise ValueError(f"range の step は正の値である必要があります: {step}")

        # step か端点のいずれかが float なら浮動小数として列挙
        is_float = any(isinstance(x, float) for x in (lo, hi, step))
        if is_float:
            n = int(round((hi - lo) / step)) + 1
            # 浮動小数誤差を 10 桁で丸める (お題マスターは小数点 1 桁程度)
            candidates: list[Any] = [round(lo + i * step, 10) for i in range(n)]
        else:
            candidates = list(range(lo, hi + 1, step))

        if not candidates:
            raise ValueError(f"range の列挙範囲が空です: {range_spec}")
        return self._rng.choice(candidates)

    def _sample_candidate(self, value_spec: dict[str, Any]) -> list[Any]:
        """
        candidate から ``choice`` 個ランダム抽出する (重複なし)

        candidate には以下が指定可能:
            - 文字列: 1 文字単位で母集団とする
            - リスト: 各要素を母集団とする
            - 特殊識別子 (``version_list`` / ``book_list`` / ``shelf_list``):
              SongRepository から該当属性のユニーク集合を解決して母集団とする

        Returns:
            choice 個のサンプル (常に list、要素順は乱数依存)

        Raises:
            ValueError: choice が母集団サイズを超える、仕様が想定外、等
        """
        candidate = value_spec.get("candidate")
        choice = value_spec.get("choice")

        if not isinstance(choice, int) or choice < 1:
            raise ValueError(
                f"choice は 1 以上の整数である必要があります: {choice}"
            )

        pool: list[Any] = self._resolve_pool(candidate)
        if choice > len(pool):
            raise ValueError(
                f"choice ({choice}) が母集団サイズ ({len(pool)}) を超えています: "
                f"candidate={candidate}"
            )

        return self._rng.sample(pool, k=choice)

    def _resolve_pool(self, candidate: Any) -> list[Any]:
        """
        candidate 指定を母集団リストに解決する
        """
        if isinstance(candidate, str):
            if candidate in self._SPECIAL_CANDIDATES:
                return self._resolve_special_candidate(candidate)
            # 通常文字列は 1 文字単位で母集団化
            if not candidate:
                raise ValueError("candidate 文字列が空です")
            return list(candidate)

        if isinstance(candidate, list):
            if not candidate:
                raise ValueError("candidate リストが空です")
            return list(candidate)

        raise ValueError(
            f"candidate は文字列またはリストである必要があります: {candidate!r}"
        )

    def _resolve_special_candidate(self, identifier: str) -> list[str]:
        """
        特殊識別子 (version_list / book_list / shelf_list) を楽曲データから解決する

        ユニーク化したうえでソート済みリストを返します。
        """
        songs = self._song_repo.all()
        if identifier == "version_list":
            values = {song.version for song in songs}
        elif identifier == "book_list":
            values = {song.book for song in songs}
        elif identifier == "shelf_list":
            values = {song.shelf for song in songs}
        else:
            # _SPECIAL_CANDIDATES と一致するため通常は到達しない
            raise ValueError(f"未知の特殊 candidate 識別子です: {identifier}")

        if not values:
            raise ValueError(
                f"特殊 candidate '{identifier}' の母集団が空です (楽曲データを確認してください)"
            )
        return sorted(values)
