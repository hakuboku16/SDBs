"""
コアモジュール

設定とログ管理のための統合モジュール
"""

from core.config import (
    Config,
    get_config,
    get_logger_config,
    set_environment,
)
from core.logger import setup_logger

__all__ = [
    "Config",
    "get_config",
    "get_logger_config",
    "set_environment",
    "setup_logger",
]
