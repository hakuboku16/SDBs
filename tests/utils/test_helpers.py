"""
helpers.py のユニットテスト
"""

from pathlib import Path

import pytest
from yaml import YAMLError

from src.utils.helpers import get_absolute_path, load_yaml, merge_dicts


class TestGetAbsolutePath:
    """
    get_absolute_path() のテスト
    """

    def test_get_absolute_path_with_str(self, test_base_dir: Path) -> None:
        """
        相対パスを正しく絶対パスに変換
        """
        result = get_absolute_path("test")
        assert result == test_base_dir / "test"

    def test_get_absolute_path_with_dot(self, test_base_dir: Path) -> None:
        """
        カレントディレクトリを示す '.' は基底パスと等しい
        """
        result = get_absolute_path(".")
        assert result == test_base_dir

    def test_get_absolute_path_with_empty_string(self, test_base_dir: Path) -> None:
        """
        空文字列は基底パスと等しい
        """
        result = get_absolute_path("")
        assert result == test_base_dir

    def test_handles_nested_path(self, test_base_dir: Path) -> None:
        """
        ネストされたパスに対応
        """
        result = get_absolute_path("test/test.txt")
        assert result == test_base_dir / "test" / "test.txt"


class TestMergeDicts:
    """
    merge_dicts() のテスト
    """

    def test_merge_non_overlapping_dicts(self) -> None:
        """
        重複しない辞書をマージ
        """
        base = {"a": 1, "b": 2}
        override = {"c": 3}

        result = merge_dicts(base, override)
        assert result == {"a": 1, "b": 2, "c": 3}

    def test_merge_overlapping_dicts(self) -> None:
        """
        重複するキーを上書き
        """
        base = {"a": 1, "b": 2}
        override = {"b": 4}

        result = merge_dicts(base, override)
        assert result == {"a": 1, "b": 4}

    def test_merge_nested_dicts(self) -> None:
        """
        ネストされた辞書を再帰的にマージ
        """
        base = {"logger": {"level": "DEBUG", "file": "app.log"}}
        override = {"logger": {"level": "INFO"}}

        result = merge_dicts(base, override)
        assert result == {"logger": {"level": "INFO", "file": "app.log"}}

    def test_merge_empty_dicts(self) -> None:
        """
        空の辞書をマージ
        """
        assert merge_dicts({}, {"a": 1}) == {"a": 1}
        assert merge_dicts({"a": 1}, {}) == {"a": 1}


class TestLoadYaml:
    """
    load_yaml() のテスト
    """

    def test_load_valid_yaml(self, valid_yaml_file) -> None:
        """
        有効なYAMLファイルを読み込み
        """
        conf = load_yaml(valid_yaml_file)
        assert conf.get("project_name") == "template"
        assert conf["logger"]["console_level"] == "DEBUG"

    def test_load_yaml_file_not_found(self) -> None:
        """
        存在しないファイルでエラーを発生
        """
        with pytest.raises(FileNotFoundError):
            load_yaml(Path("nonexistent.yaml"))

    def test_load_yaml_with_invalid_format(self, tmp_path) -> None:
        """
        不正なYAML形式でエラーを発生
        """
        yaml_file = tmp_path / "invalid.yaml"
        yaml_file.write_text("invalid: yaml: content: [", encoding="utf-8")

        with pytest.raises(YAMLError):
            load_yaml(yaml_file)

    def test_load_yaml_with_empty_file(self, tmp_path) -> None:
        """
        空のYAMLファイルは空のdictを返す
        """
        yaml_file = tmp_path / "empty.yaml"
        yaml_file.write_text("", encoding="utf-8")

        result = load_yaml(yaml_file)
        assert result == {}
