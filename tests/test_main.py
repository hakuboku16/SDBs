"""
main.py のユニットテスト

ensure_env_loaded(), get_environment(), get_discord_token(), main() の
基本的な動作を検証します。Bot.run は実際にネットワーク接続が走るため
すべて mock で置き換えます。
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


class TestGetDiscordToken:
    """
    get_discord_token() のテスト
    """

    @patch("src.main.ensure_env_loaded")
    @patch.dict("os.environ", {"DISCORD_TOKEN": "abc123"}, clear=True)
    def test_returns_token(self, mock_ensure_env_loaded):
        """
        DISCORD_TOKEN が設定されていればその値が返る
        """
        assert main_module.get_discord_token() == "abc123"

    @patch("src.main.ensure_env_loaded")
    @patch.dict("os.environ", {"DISCORD_TOKEN": "  abc123  "}, clear=True)
    def test_strips_whitespace(self, mock_ensure_env_loaded):
        """
        前後の空白は除去される
        """
        assert main_module.get_discord_token() == "abc123"

    @patch("src.main.ensure_env_loaded")
    @patch.dict("os.environ", {}, clear=True)
    def test_raises_when_unset(self, mock_ensure_env_loaded):
        """
        未設定なら RuntimeError が送出される
        """
        with pytest.raises(RuntimeError, match="DISCORD_TOKEN"):
            main_module.get_discord_token()

    @patch("src.main.ensure_env_loaded")
    @patch.dict("os.environ", {"DISCORD_TOKEN": "   "}, clear=True)
    def test_raises_when_blank(self, mock_ensure_env_loaded):
        """
        空白のみでも未設定として扱う
        """
        with pytest.raises(RuntimeError, match="DISCORD_TOKEN"):
            main_module.get_discord_token()


class TestMainFunction:
    """
    main() 関数の振る舞いを検証

    Bot.run はネットワーク I/O を伴うためすべて mock 経由で呼び出されることを確認します。
    """

    def _patch_common(self):
        """
        main() 内部で呼ばれる依存関係をまとめてパッチするコンテキスト
        """
        return [
            patch("src.main.get_environment", return_value="test"),
            patch("src.main.set_environment"),
            patch("src.main.get_config"),
            patch("src.main.get_discord_config"),
            patch("src.main.setup_logger"),
            patch("src.main.SDBsBot"),
        ]

    def test_main_happy_path_runs_bot_with_token(self):
        """
        正常系: SDBsBot がインスタンス化され `bot.run(token)` が呼ばれる
        """
        fake_config = MagicMock()
        fake_config.raw_config = {"project_name": "template", "version": "1.0"}
        fake_logger = MagicMock()
        fake_discord_config = MagicMock()
        fake_bot = MagicMock()

        with patch("src.main.get_environment", return_value="test") as mock_get_env, patch(
            "src.main.set_environment"
        ) as mock_set_env, patch(
            "src.main.get_config", return_value=fake_config
        ) as mock_get_config, patch(
            "src.main.get_discord_config", return_value=fake_discord_config
        ) as mock_get_discord_config, patch(
            "src.main.setup_logger", return_value=fake_logger
        ) as mock_setup_logger, patch(
            "src.main.get_discord_token", return_value="token-xyz"
        ) as mock_get_token, patch(
            "src.main.SDBsBot", return_value=fake_bot
        ) as mock_bot_cls:

            main_module.main()

        # 環境ロード・設定取得・ロガー初期化が実施される
        mock_get_env.assert_called_once()
        mock_set_env.assert_called_once_with("test")
        mock_get_config.assert_called_once()
        mock_setup_logger.assert_called_once()
        mock_get_token.assert_called_once()
        mock_get_discord_config.assert_called_once()

        # SDBsBot に DiscordConfig が渡されインスタンス化される
        mock_bot_cls.assert_called_once_with(fake_discord_config)
        # bot.run はトークンを渡して 1 回だけ呼ばれる
        fake_bot.run.assert_called_once_with("token-xyz")

        # 起動・終了ログが出る
        fake_logger.info.assert_any_call("Bot を起動します")
        fake_logger.info.assert_any_call("Bot を終了します")

    def test_main_exits_when_token_missing(self):
        """
        DISCORD_TOKEN 未設定なら SystemExit(1) で終了し、Bot は起動されない
        """
        fake_config = MagicMock()
        fake_config.raw_config = {"project_name": "template", "version": "1.0"}
        fake_logger = MagicMock()
        fake_bot = MagicMock()

        with patch("src.main.get_environment", return_value="test"), patch(
            "src.main.set_environment"
        ), patch("src.main.get_config", return_value=fake_config), patch(
            "src.main.get_discord_config"
        ) as mock_get_discord_config, patch(
            "src.main.setup_logger", return_value=fake_logger
        ), patch(
            "src.main.get_discord_token",
            side_effect=RuntimeError("DISCORD_TOKEN が未設定"),
        ), patch(
            "src.main.SDBsBot", return_value=fake_bot
        ) as mock_bot_cls:

            with pytest.raises(SystemExit) as exc_info:
                main_module.main()

        # 終了コード 1 で SystemExit
        assert exc_info.value.code == 1

        # Bot は構築されず run も呼ばれない
        mock_bot_cls.assert_not_called()
        fake_bot.run.assert_not_called()
        mock_get_discord_config.assert_not_called()

        # エラー内容がロガーに残る
        assert any(
            "DISCORD_TOKEN" in str(call_args)
            for call_args in fake_logger.error.call_args_list
        )

    def test_main_logs_and_reraises_when_bot_run_fails(self):
        """
        bot.run() が例外を投げた場合、ロガーへ出力した上で例外を再送出する
        (例外は握りつぶさない)
        """
        fake_config = MagicMock()
        fake_config.raw_config = {"project_name": "template", "version": "1.0"}
        fake_logger = MagicMock()
        fake_bot = MagicMock()
        fake_bot.run.side_effect = RuntimeError("Bot 起動失敗")

        with patch("src.main.get_environment", return_value="test"), patch(
            "src.main.set_environment"
        ), patch("src.main.get_config", return_value=fake_config), patch(
            "src.main.get_discord_config"
        ), patch(
            "src.main.setup_logger", return_value=fake_logger
        ), patch(
            "src.main.get_discord_token", return_value="token-xyz"
        ), patch(
            "src.main.SDBsBot", return_value=fake_bot
        ):

            with pytest.raises(RuntimeError, match="Bot 起動失敗"):
                main_module.main()

        # 終了ログは finally で出る
        fake_logger.info.assert_any_call("Bot を終了します")
        # エラーがロガーに出力される
        assert fake_logger.error.called
