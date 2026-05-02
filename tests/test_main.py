"""
main.py のユニットテスト

ensure_env_loaded(), get_environment(), main() の基本的な動作を検証します。
"""

import sys
from unittest.mock import MagicMock, patch

import pytest

from src import main as main_module


class TestEnsureEnvLoaded:
    """
    ensure_env_loaded() のテスト
    """

    @patch("src.main.load_dotenv")
    @patch("src.main.get_absolute_path")
    def test_no_env_file(self, mock_get_path, mock_load, tmp_path):
        """
        .env ファイルが存在しない場合は何も読み込まれない
        """
        mock_get_path.return_value = tmp_path / ".env"

        main_module.ensure_env_loaded()
        assert not mock_load.called

    @patch("src.main.load_dotenv")
    @patch("src.main.get_absolute_path")
    def test_env_file_exists(self, mock_get_path, mock_load, tmp_path):
        """
        .env ファイルが存在すれば load_dotenv が呼ばれる
        """
        env_file = tmp_path / ".env"
        env_file.write_text("ENVIRONMENT=test", encoding="utf-8")
        mock_get_path.return_value = env_file

        main_module.ensure_env_loaded()
        assert mock_load.called


class TestGetEnvironment:
    """
    get_environment() のテスト
    """

    def test_cli_argument(self, monkeypatch):
        """
        コマンドライン引数 --env が優先される
        """
        monkeypatch.setattr(sys, "argv", ["prog", "--env", "test"])
        result = main_module.get_environment()
        assert result == "test"

    @patch("src.main.ensure_env_loaded")
    @patch.dict("os.environ", {"ENVIRONMENT": "test"})
    def test_env_var(self, mock_ensure_env_loaded):
        """
        ENVIRONMENT 環境変数が使用される
        """
        result = main_module.get_environment()
        assert result == "test"

    @patch("src.main.ensure_env_loaded")
    @patch.dict("os.environ", {"ENVIRONMENT": "  test "})
    def test_env_var_whitespace_case(self, mock_ensure_env_loaded):
        """
        環境変数の前後空白や大文字小文字が正規化される
        """
        result = main_module.get_environment()
        assert result == "test"

    @patch("src.main.ensure_env_loaded")
    @patch.dict("os.environ", {"ENVIRONMENT": "invalid"})
    def test_env_var_invalid(self, mock_ensure_env_loaded):
        """
        無効な値が指定されると ValueError
        """
        with pytest.raises(ValueError):
            main_module.get_environment()

    @patch("src.main.ensure_env_loaded")
    @patch.dict("os.environ", {}, clear=True)
    def test_default(self, mock_ensure_env_loaded):
        """
        何も指定がなければ development を返す
        """
        assert main_module.get_environment() == "development"


class TestMainFunction:
    """
    main() 関数の振る舞いを検証
    """

    @patch("src.main.get_environment")
    @patch("src.main.set_environment")
    @patch("src.main.get_config")
    @patch("src.main.setup_logger")
    def test_main_happy_path(
        self, mock_setup_logger, mock_get_config, mock_set_env, mock_get_env
    ):
        """
        何も問題がなければ各ヘルパーが呼び出されログが記録される
        """
        mock_get_env.return_value = "test"
        fake_config = MagicMock()
        fake_config.raw_config = {"project_name": "template", "version": "1.0"}
        mock_get_config.return_value = fake_config
        fake_logger = MagicMock()
        mock_setup_logger.return_value = fake_logger

        main_module.main()

        mock_get_env.assert_called_once()
        mock_set_env.assert_called_once_with("test")
        mock_get_config.assert_called_once()
        mock_setup_logger.assert_called_once()

        fake_logger.info.assert_any_call("処理を開始します")
        fake_logger.info.assert_any_call("処理を終了します")
