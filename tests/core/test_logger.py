"""
logger.py のユニットテスト

setup_logger() 関数の動作をテストします。
"""

import logging
from logging import DEBUG, ERROR, WARNING
from logging.handlers import RotatingFileHandler
from unittest.mock import patch

from src.core.logger import setup_logger


class TestSetupLogger:
    """
    setup_logger() のテスト
    """

    # ==================================================
    # テストメソッド
    # ==================================================
    @patch("src.core.logger.get_logger_config")
    def test_setup_logger_returns_logger_instance(
        self, mock_config, mock_logger_config
    ) -> None:
        """
        setup_logger() が Logger インスタンスを返す
        """
        mock_config.return_value = mock_logger_config

        logger = setup_logger(name="test_returns_instance")
        assert isinstance(logger, logging.Logger)

    @patch("src.core.logger.get_logger_config")
    def test_setup_logger_with_custom_name(self, mock_config, mock_logger_config) -> None:
        """
        カスタム名でロガーが作成される
        """
        mock_config.return_value = mock_logger_config

        custom_name = "my_custom_logger"
        logger = setup_logger(name=custom_name)
        assert logger.name == custom_name

    @patch("src.core.logger.get_logger_config")
    def test_setup_logger_sets_debug_level(self, mock_config, mock_logger_config) -> None:
        """
        ロガーのレベルが DEBUG に設定される
        """
        mock_config.return_value = mock_logger_config

        logger = setup_logger(name="test_debug_level")
        assert logger.level == DEBUG

    @patch("src.core.logger.get_logger_config")
    def test_setup_logger_adds_handlers(self, mock_config, mock_logger_config) -> None:
        """
        コンソールハンドラとファイルハンドラが追加される
        """
        mock_config.return_value = mock_logger_config

        logger = setup_logger(name="test_handlers_added")
        handler_types = {type(h).__name__ for h in logger.handlers}
        assert "StreamHandler" in handler_types
        assert "RotatingFileHandler" in handler_types
        assert len(logger.handlers) == 2

    @patch("src.core.logger.get_logger_config")
    def test_setup_logger_avoids_duplicate_handlers(
        self, mock_config, mock_logger_config
    ) -> None:
        """
        ハンドラが既に設定されている場合は重複を避ける
        """
        mock_config.return_value = mock_logger_config

        logger = setup_logger(name="test_duplicate_avoidance")
        initial_handler_count = len(logger.handlers)
        logger_again = setup_logger(name="test_duplicate_avoidance")
        assert len(logger_again.handlers) == initial_handler_count
        assert logger is logger_again
        assert initial_handler_count == 2

    @patch("src.core.logger.get_logger_config")
    def test_setup_logger_creates_log_directory(
        self, mock_config, mock_logger_config
    ) -> None:
        """
        ロガー設定に指定されたディレクトリが作成される
        """
        mock_config.return_value = mock_logger_config

        setup_logger(name="test_directory_creation")
        assert mock_logger_config.log_dir.exists()
        assert mock_logger_config.log_dir.is_dir()

    @patch("src.core.logger.get_logger_config")
    def test_setup_logger_formatter_is_set(self, mock_config, mock_logger_config) -> None:
        """
        すべてのハンドラにフォーマッターが設定される
        """
        mock_config.return_value = mock_logger_config

        logger = setup_logger(name="test_formatter_set")
        for handler in logger.handlers:
            assert handler.formatter is not None

    @patch("src.core.logger.get_logger_config")
    def test_setup_logger_uses_rotating_file_handler(
        self, mock_config, mock_logger_config
    ) -> None:
        """
        ファイルハンドラが RotatingFileHandler である
        """
        mock_config.return_value = mock_logger_config

        logger = setup_logger(name="test_rotating_handler")
        file_handler = self._get_handler_by_type(logger, RotatingFileHandler)
        assert file_handler is not None
        assert isinstance(file_handler, RotatingFileHandler)

    @patch("src.core.logger.get_logger_config")
    def test_setup_logger_console_handler_level(
        self, mock_config, mock_logger_config
    ) -> None:
        """
        コンソールハンドラのレベルが正しく設定される
        """
        mock_logger_config.console_level = "WARNING"
        mock_config.return_value = mock_logger_config

        logger = setup_logger(name="test_console_level")
        stream_handler = self._get_handler_by_type(logger, logging.StreamHandler)
        assert stream_handler is not None
        assert stream_handler.level == WARNING

    @patch("src.core.logger.get_logger_config")
    def test_setup_logger_file_handler_level(self, mock_config, mock_logger_config) -> None:
        """
        ファイルハンドラのレベルが正しく設定される
        """
        mock_logger_config.file_level = "ERROR"
        mock_config.return_value = mock_logger_config

        logger = setup_logger(name="test_file_level")
        file_handler = self._get_handler_by_type(logger, RotatingFileHandler)
        assert file_handler is not None
        assert file_handler.level == ERROR

    # ==================================================
    # ヘルパーメソッド
    # ==================================================
    @staticmethod
    def _get_handler_by_type(
        logger: logging.Logger, handler_type: type
    ) -> logging.Handler | None:
        """
        指定された型のハンドラをロガーから取得

        Args:
            logger: 検索対象のロガー
            handler_type: 検索するハンドラの型

        Returns:
            logging.Handler | None: 見つかったハンドラ、見つからない場合は None
        """
        for handler in logger.handlers:
            if isinstance(handler, handler_type):
                return handler
        return None
