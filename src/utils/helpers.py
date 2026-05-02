"""
ヘルパー関数集

プロジェクト全体で共通に使用するユーティリティ関数を定義します。
"""

from pathlib import Path
from typing import Any

import yaml


def get_absolute_path(relative_path: str) -> Path:
    """
    相対パスを基底パスからの絶対パスに変換

    Args:
        relative_path: 基底パスからの相対パス

    Returns:
        基底パスからの絶対パス
    """
    base_path = Path(__file__).resolve().parents[2]
    return base_path / relative_path


def merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """
    2つの辞書を再帰的にマージする

    override の値が base の値を上書きします。
    ネストした辞書も再帰的にマージされます。

    Args:
        base: ベースとなる辞書
        override: 上書きする辞書

    Returns:
        マージされた辞書
    """
    result = base.copy()

    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            # ネストした辞書の場合は再帰的にマージ
            result[key] = merge_dicts(result[key], value)
        else:
            # それ以外は上書き
            result[key] = value

    return result


def load_yaml(file_path: Path) -> dict[str, Any]:
    """
    YAMLファイルを読み込む

    Args:
        file_path: YAMLファイルのパス

    Returns:
        パースされたデータ

    Raises:
        FileNotFoundError: ファイルが存在しない場合
        yaml.YAMLError: YAML形式が不正な場合
    """
    with open(file_path, "r", encoding="utf-8") as f:
        result = yaml.safe_load(f)
    if result is None:
        return {}
    return result
