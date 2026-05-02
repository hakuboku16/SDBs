"""
config.py のユニットテスト

LoggerConfig, Config, set_environment などの動作をテストします。
"""

from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from src.core import config as config_module
from src.core.config import LoggerConfig


class TestLoggerConfig:
    """
    LoggerConfig (Pydantic モデル) のテスト
    """

    def test_validate_success(self):
        """
        必須項目が揃っていれば LoggerConfig が返る
        """
        result = LoggerConfig(
            console_level="DEBUG",
            file_level="INFO",
            format="fmt",
            log_dir=Path("logs"),
            log_file="python.log",
            max_bytes=1,
            backup_count=2,
        )
        assert result.console_level == "DEBUG"
        assert result.file_level == "INFO"
        assert result.format == "fmt"
        assert isinstance(result.log_dir, Path)
        assert result.log_file == "python.log"
        assert result.max_bytes == 1
        assert result.backup_count == 2

    def test_validate_missing_required(self):
        """
        必須項目が欠落している場合は ValidationError
        """
        with pytest.raises(ValidationError):
            LoggerConfig.model_validate({"console_level": "DEBUG"})

    def test_validate_empty_string_required(self):
        """
        必須項目が空文字列の場合は ValidationError
        """
        with pytest.raises(ValidationError):
            LoggerConfig(console_level="", file_level="INFO", format="fmt")

    def test_validate_invalid_log_level(self):
        """
        無効なログレベルの場合は ValidationError
        """
        with pytest.raises(ValidationError):
            LoggerConfig(console_level="INVALID", file_level="INFO", format="fmt")

    def test_validate_log_level_normalized_to_uppercase(self):
        """
        小文字のログレベルが大文字に正規化される
        """
        result = LoggerConfig(console_level="debug", file_level="info", format="fmt")
        assert result.console_level == "DEBUG"
        assert result.file_level == "INFO"

    def test_default_values(self):
        """
        オプション項目が省略された場合にデフォルト値が使われる
        """
        result = LoggerConfig(
            console_level="DEBUG",
            file_level="INFO",
            format="fmt",
        )
        assert isinstance(result.log_dir, Path)
        assert result.log_file == "python.log"
        assert result.max_bytes == 10485760
        assert result.backup_count == 5


class TestConfig:
    """
    Config クラスのテスト
    """

    @patch("src.core.config.get_absolute_path")
    @patch("src.core.config.load_yaml")
    @patch("src.core.config.merge_dicts")
    def test_init_and_env_merge(self, mock_merge, mock_load, mock_abs, valid_yaml_file):
        """
        初期化で get_absolute_path, load_yaml, merge_dicts を呼ぶ
        """
        base = {
            "logger": {"console_level": "DEBUG", "file_level": "DEBUG", "format": "fmt"}
        }
        mock_abs.return_value = valid_yaml_file
        mock_load.return_value = base
        mock_merge.return_value = base

        config_module.Config(environment="test")
        assert mock_abs.call_count == 2
        assert mock_load.call_count == 2
        assert mock_merge.call_count == 1

    def test_singleton_get_and_reset(self):
        """
        get() でシングルトンが返り、reset() でキャッシュが消える
        """
        config_module.Config._instances.clear()

        c1 = config_module.Config.get("test")
        c2 = config_module.Config.get("test")
        assert c1 is c2

        config_module.Config.reset("test")
        assert "test" not in config_module.Config._instances

        config_module.Config.reset()
        assert config_module.Config._instances == {}

    def test_get_logger_config(self):
        """
        get_logger_config() が LoggerConfig インスタンスを返す
        """
        conf = config_module.Config()
        conf.raw_config = {
            "logger": {
                "console_level": "DEBUG",
                "file_level": "INFO",
                "format": "fmt",
            }
        }
        result = conf.get_logger_config()
        assert isinstance(result, LoggerConfig)
        assert result.console_level == "DEBUG"

    def test_get_logger_config_missing_required(self):
        """
        必須項目が欠落している場合は ValidationError
        """
        conf = config_module.Config()
        conf.raw_config = {"logger": {}}
        with pytest.raises(ValidationError):
            conf.get_logger_config()


class TestGlobalEnvironment:
    """
    グローバル環境管理のテスト
    """

    def test_set_and_get_environment(self):
        """
        set_environment() で環境が切り替わる
        """
        config_module.set_environment("production")
        assert config_module._get_current_environment() == "production"

        config_module.set_environment("test")
        assert config_module._get_current_environment() == "test"


class TestHelperFunctions:
    """
    ヘルパー関数のテスト
    """

    @patch("src.core.config.Config.get")
    @patch("src.core.config._get_current_environment")
    def test_get_config_non_environment(self, mock_get_env, mock_get_conf):
        """
        環境変数がない場合 _get_current_environment() を呼び出す
        """
        mock_get_env.return_value = "env"
        mock_get_conf.return_value = "dummy"

        config_module.get_config()
        assert mock_get_env.called
        assert mock_get_conf.called

    @patch("src.core.config.Config.get")
    def test_get_config(self, mock_get):
        """
        get_config() が Config.get() を呼ぶ
        """
        mock_get.return_value = "dummy"

        assert config_module.get_config("test") == "dummy"
        assert mock_get.called

    @patch("src.core.config.get_config")
    def test_get_logger_config(self, mock_get_config):
        """
        get_logger_config() が get_config().get_logger_config() を呼ぶ
        """
        from unittest.mock import MagicMock
        mock_conf = MagicMock()
        mock_get_config.return_value = mock_conf

        config_module.get_logger_config("test")
        assert mock_conf.get_logger_config.called
