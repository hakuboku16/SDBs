"""
バリデーション関数集

データの妥当性チェック用のユーティリティ関数を定義します。
"""

from typing import Any


def is_numeric(value: Any) -> bool:
    """
    引数が数字かどうかを判定する関数

    Args:
        value: 判定対象の値

    Returns:
        bool: 数字の場合True、それ以外はFalse
    """
    if isinstance(value, bool):
        return False

    if isinstance(value, (int, float)):
        return True

    if isinstance(value, str):
        try:
            float(value)
            return True
        except ValueError:
            return False

    return False


def is_natural_number(value: Any) -> bool:
    """
    引数が自然数かどうかを判定する関数
    自然数は正の整数（1, 2, 3, ...）として定義

    Args:
        value: 判定対象の値

    Returns:
        bool: 自然数の場合True、それ以外はFalse
    """
    if isinstance(value, bool):
        return False

    if isinstance(value, int):
        return value > 0

    if isinstance(value, str):
        try:
            num = int(value)
            return num > 0
        except ValueError:
            return False

    if isinstance(value, float):
        return value > 0 and value == int(value)

    return False


def is_not_empty(value: Any) -> bool:
    """
    引数が空でないかを判定する関数
    文字列の場合はホワイトスペース（スペース、タブ、改行など）を除去してから判定

    Args:
        value: 判定対象の値

    Returns:
        bool: 空でない場合True、空の場合はFalse
    """
    if value is None:
        return False

    if isinstance(value, str):
        return len(value.strip()) > 0

    if isinstance(value, (list, tuple, dict, set)):
        return len(value) > 0

    return True
