"""
ログ設定モジュール

コンソールとファイルへの出力を設定し、ローテーションにも対応します。
"""

import logging
from logging.handlers import RotatingFileHandler

from core.config import get_logger_config


def setup_logger(name: str) -> logging.Logger:
    """
    ロガーを設定して返す

    呼び出し元で __name__ を渡すこと。
    他のモジュールで同じロガーを使う場合は logging.getLogger(name) で取得する。

    Args:
        name: ロガー名。main.py では __name__ ("__main__") を渡す
    """
    # LoggerConfig の取得
    logger_config = get_logger_config()

    # ロガーの作成
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # すでにハンドラが設定されている場合は重複を避ける
    if _has_handlers(logger):
        return logger

    # フォーマッターの作成
    formatter = logging.Formatter(logger_config.format)

    # コンソールハンドラの設定
    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, logger_config.console_level))
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # ログディレクトリの作成
    logger_config.log_dir.mkdir(parents=True, exist_ok=True)

    # ファイルハンドラの設定(ローテーション対応)
    log_file = logger_config.log_dir / logger_config.log_file
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=logger_config.max_bytes,
        backupCount=logger_config.backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(getattr(logging, logger_config.file_level))
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


def _has_handlers(logger: logging.Logger) -> bool:
    """
    ロガーがハンドラを持っているかを確認

    StreamHandler と RotatingFileHandler の両方が設定されているかチェックします。

    Args:
        logger: チェック対象のロガー

    Returns:
        bool: 必要なハンドラがすべて設定されている場合True
    """
    handler_types = {type(h).__name__ for h in logger.handlers}
    return "StreamHandler" in handler_types and "RotatingFileHandler" in handler_types
