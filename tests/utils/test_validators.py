"""
validators.py のユニットテスト

is_numeric、is_natural_number、is_not_empty 関数のテストを行います。
"""

import pytest

from src.utils.validators import (
    is_natural_number,
    is_not_empty,
    is_numeric,
)


class TestIsNumeric:
    """
    is_numeric() 関数のテスト
    """

    @pytest.mark.parametrize(
        "value,expected",
        [
            # 整数
            (1, True),
            (-1, True),
            (0, True),
            # 浮動小数点数
            (3.14, True),
            (-3.14, True),
            # 数字文字列
            ("1", True),
            ("-1", True),
            ("0", True),
            ("3.14", True),
            # スペース付き数字文字列
            (" 1 ", True),
            ("　-1 ", True),
            (" 0　", True),
            ("　3.14　", True),
            # 特殊な浮動小数点値
            ("inf", True),
            ("-inf", True),
            ("nan", True),
            # 非数値
            ("abc", False),
            ("12.34.56", False),
            ("", False),
            # ブール値（例外）
            (True, False),
            (False, False),
            # None
            (None, False),
            # コレクション
            ([1, 2, 3], False),
            ({"key": "value"}, False),
        ],
        ids=[
            "positive_int",
            "negative_int",
            "zero",
            "positive_float",
            "negative_float",
            "numeric_string",
            "negative_string",
            "zero_string",
            "float_string",
            "space_before_num",
            "ideographic_space_negative",
            "space_after_num",
            "ideographic_space_float",
            "inf",
            "negative_inf",
            "nan",
            "non_numeric_string",
            "invalid_float_string",
            "empty_string",
            "bool_true",
            "bool_false",
            "none",
            "list",
            "dict",
        ],
    )
    def test_is_numeric(self, value, expected) -> None:
        """is_numeric() の各パターンをテスト"""
        assert is_numeric(value) is expected


class TestIsNaturalNumber:
    """
    is_natural_number() 関数のテスト
    """

    @pytest.mark.parametrize(
        "value,expected",
        [
            # 自然数（整数）
            (1, True),
            # 自然数（浮動小数点の整数値）
            (1.0, True),
            (1e10, True),
            # 非自然数（負の整数）
            (-1, False),
            # 非自然数（0）
            (0, False),
            # 非自然数（非整数の浮動小数点）
            (3.14, False),
            (-3.14, False),
            (-1.0, False),
            # 自然数を表す文字列
            ("1", True),
            # 非自然数を表す文字列
            ("-1", False),
            ("0", False),
            ("abc", False),
            ("12.34.56", False),
            ("", False),
            # ブール値（例外）
            (True, False),
            (False, False),
            # None
            (None, False),
            # コレクション
            ([1, 2, 3], False),
            ({"key": "value"}, False),
        ],
        ids=[
            "positive_int",
            "positive_float_integer_value",
            "positive_float_large_value",
            "negative_int",
            "zero",
            "positive_float_non_integer",
            "negative_float_non_integer",
            "negative_float_integer_value",
            "natural_number_string",
            "negative_string",
            "zero_string",
            "non_numeric_string",
            "invalid_float_string",
            "empty_string",
            "bool_true",
            "bool_false",
            "none",
            "list",
            "dict",
        ],
    )
    def test_is_natural_number(self, value, expected) -> None:
        """is_natural_number() の各パターンをテスト"""
        assert is_natural_number(value) is expected


class TestIsNotEmpty:
    """
    is_not_empty() 関数のテスト
    """

    @pytest.mark.parametrize(
        "value,expected",
        [
            # 空データ
            (None, False),
            ("", False),
            (" ", False),
            ("　", False),
            ("\t", False),
            ("\n", False),
            ([], False),
            ((), False),
            ({}, False),
            (set(), False),
            # 非空データ（文字列）
            ("hello", True),
            # 非空データ（リスト）
            ([1, 2, 3], True),
            ([None], True),
            # 非空データ（タプル）
            ((1, 2, 3), True),
            # 非空データ（辞書）
            ({"key": "value"}, True),
            # 非空データ（セット）
            ({1, 2, 3}, True),
            # 非空データ（数値）
            (1, True),
            (0, True),
            (-1, True),
            (0.0, True),
            (3.14, True),
            # 非空データ（ブール値）
            (True, True),
            (False, True),
        ],
        ids=[
            "none",
            "empty_string",
            "space_string",
            "ideographic_space",
            "tab_string",
            "newline_string",
            "empty_list",
            "empty_tuple",
            "empty_dict",
            "empty_set",
            "non_empty_string",
            "non_empty_list",
            "list_with_none",
            "non_empty_tuple",
            "non_empty_dict",
            "non_empty_set",
            "positive_int",
            "zero",
            "negative_int",
            "zero_float",
            "positive_float",
            "bool_true",
            "bool_false",
        ],
    )
    def test_is_not_empty(self, value, expected) -> None:
        """is_not_empty() の各パターンをテスト"""
        assert is_not_empty(value) is expected
