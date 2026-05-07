"""
config.py のユニットテスト

LoggerConfig, DiscordConfig, SessionConfig, AssetsConfig, Config,
set_environment などの動作をテストします。
"""

from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from src.core import config as config_module
from src.core.config import (
    AssetsConfig,
    DiscordConfig,
    LoggerConfig,
    SessionConfig,
)


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


class TestDiscordConfig:
    """
    DiscordConfig (Pydantic モデル) のテスト
    """

    def test_validate_success_with_defaults(self):
        """
        既定値のみで DiscordConfig が生成される
        """
        result = DiscordConfig()
        assert result.session_timeout_minutes == 30
        assert result.warning_minutes_before_end == 10
        assert result.command_sync_guilds == []
        assert result.log_channel_id is None
        assert result.result_channel_id is None

    def test_validate_success_with_all_fields(self):
        """
        全項目を指定して DiscordConfig が生成される
        """
        result = DiscordConfig(
            session_timeout_minutes=60,
            warning_minutes_before_end=15,
            command_sync_guilds=[111, 222],
            log_channel_id=333,
            result_channel_id=444,
        )
        assert result.session_timeout_minutes == 60
        assert result.warning_minutes_before_end == 15
        assert result.command_sync_guilds == [111, 222]
        assert result.log_channel_id == 333
        assert result.result_channel_id == 444

    def test_validate_non_positive_timeout(self):
        """
        session_timeout_minutes が 0 以下の場合は ValidationError
        """
        with pytest.raises(ValidationError):
            DiscordConfig(session_timeout_minutes=0, warning_minutes_before_end=1)

    def test_validate_non_positive_warning(self):
        """
        warning_minutes_before_end が 0 以下の場合は ValidationError
        """
        with pytest.raises(ValidationError):
            DiscordConfig(session_timeout_minutes=10, warning_minutes_before_end=0)

    def test_validate_warning_ge_timeout(self):
        """
        warning_minutes_before_end が session_timeout_minutes 以上の場合は ValidationError
        """
        with pytest.raises(ValidationError):
            DiscordConfig(session_timeout_minutes=10, warning_minutes_before_end=10)

        with pytest.raises(ValidationError):
            DiscordConfig(session_timeout_minutes=10, warning_minutes_before_end=20)


class TestSessionConfig:
    """
    SessionConfig (Pydantic モデル) のテスト
    """

    def test_validate_success_with_defaults(self):
        """
        既定値のみで SessionConfig が生成される
        """
        result = SessionConfig()
        assert result.default_panel_count == 9
        assert result.allowed_panel_counts == [4, 9, 16, 25]
        assert result.mosaic_levels == {
            "なし": 300,
            "弱": 150,
            "中": 90,
            "強": 45,
            "最強": 27,
        }

    def test_validate_success_with_custom_values(self):
        """
        値を指定して SessionConfig が生成される
        """
        result = SessionConfig(
            default_panel_count=4,
            allowed_panel_counts=[4, 16],
            mosaic_levels={"none": 100, "strong": 20},
        )
        assert result.default_panel_count == 4
        assert result.allowed_panel_counts == [4, 16]
        assert result.mosaic_levels == {"none": 100, "strong": 20}

    def test_validate_default_not_in_allowed(self):
        """
        default_panel_count が allowed_panel_counts に含まれない場合は ValidationError
        """
        with pytest.raises(ValidationError):
            SessionConfig(default_panel_count=9, allowed_panel_counts=[4, 16])

    def test_validate_allowed_contains_non_square(self):
        """
        allowed_panel_counts に平方数でない値が含まれる場合は ValidationError
        """
        with pytest.raises(ValidationError):
            SessionConfig(default_panel_count=4, allowed_panel_counts=[4, 10])

    def test_validate_allowed_contains_non_positive(self):
        """
        allowed_panel_counts に 0 以下の値が含まれる場合は ValidationError
        """
        with pytest.raises(ValidationError):
            SessionConfig(default_panel_count=4, allowed_panel_counts=[0, 4])

    def test_validate_allowed_empty(self):
        """
        allowed_panel_counts が空の場合は ValidationError
        """
        with pytest.raises(ValidationError):
            SessionConfig(default_panel_count=4, allowed_panel_counts=[])

    def test_validate_mosaic_block_non_positive(self):
        """
        mosaic_levels の block 画素数が 0 以下の場合は ValidationError
        """
        with pytest.raises(ValidationError):
            SessionConfig(mosaic_levels={"なし": 0})

    def test_validate_mosaic_levels_empty(self):
        """
        mosaic_levels が空の場合は ValidationError
        """
        with pytest.raises(ValidationError):
            SessionConfig(mosaic_levels={})


class TestAssetsConfig:
    """
    AssetsConfig (Pydantic モデル) のテスト
    """

    def test_validate_success_resolves_to_absolute(self):
        """
        相対パスが get_absolute_path によって絶対パスに解決される
        """
        result = AssetsConfig(
            songs_json="assets/data/all_songs.json",
            topics_json="assets/data/all_topics.json",
            images_dir="assets/images",
        )
        assert isinstance(result.songs_json, Path)
        assert result.songs_json.is_absolute()
        assert result.songs_json.name == "all_songs.json"
        assert isinstance(result.topics_json, Path)
        assert result.topics_json.is_absolute()
        assert result.topics_json.name == "all_topics.json"
        assert isinstance(result.images_dir, Path)
        assert result.images_dir.is_absolute()
        assert result.images_dir.name == "images"

    def test_validate_missing_required(self):
        """
        必須項目が欠落している場合は ValidationError
        """
        with pytest.raises(ValidationError):
            AssetsConfig.model_validate({"songs_json": "assets/data/all_songs.json"})

    def test_validate_empty_string(self):
        """
        必須項目が空文字列の場合は ValidationError
        """
        with pytest.raises(ValidationError):
            AssetsConfig(
                songs_json="",
                topics_json="assets/data/all_topics.json",
                images_dir="assets/images",
            )

    def test_validate_none_value(self):
        """
        必須項目に None が指定された場合は ValidationError
        """
        with pytest.raises(ValidationError):
            AssetsConfig.model_validate(
                {
                    "songs_json": None,
                    "topics_json": "assets/data/all_topics.json",
                    "images_dir": "assets/images",
                }
            )


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

    @patch.dict("os.environ", {}, clear=True)
    def test_get_discord_config(self):
        """
        get_discord_config() が DiscordConfig インスタンスを返す

        チャンネル ID は .env で管理する仕様のため、yaml に書いても
        環境変数未設定なら None になることをあわせて検証する。
        """
        conf = config_module.Config()
        conf.raw_config = {
            "discord": {
                "session_timeout_minutes": 30,
                "warning_minutes_before_end": 10,
                "command_sync_guilds": [111],
            }
        }
        result = conf.get_discord_config()
        assert isinstance(result, DiscordConfig)
        assert result.session_timeout_minutes == 30
        assert result.command_sync_guilds == [111]
        assert result.log_channel_id is None
        assert result.result_channel_id is None

    @patch.dict(
        "os.environ",
        {"LOG_CHANNEL_ID": "222", "RESULT_CHANNEL_ID": "333"},
        clear=True,
    )
    def test_get_discord_config_reads_channel_ids_from_env(self):
        """
        通知先チャンネル ID は環境変数 (.env) から読み込まれる
        """
        conf = config_module.Config()
        conf.raw_config = {
            "discord": {
                "session_timeout_minutes": 30,
                "warning_minutes_before_end": 10,
            }
        }
        result = conf.get_discord_config()
        assert result.log_channel_id == 222
        assert result.result_channel_id == 333

    @patch.dict(
        "os.environ",
        {"LOG_CHANNEL_ID": "999", "RESULT_CHANNEL_ID": "888"},
        clear=True,
    )
    def test_get_discord_config_env_overrides_yaml(self):
        """
        yaml にチャンネル ID が残っていても環境変数が優先される
        (移行期間中の互換性は意図せず混入したケースの挙動を明示)
        """
        conf = config_module.Config()
        conf.raw_config = {
            "discord": {
                "session_timeout_minutes": 30,
                "warning_minutes_before_end": 10,
                "log_channel_id": 111,
                "result_channel_id": 222,
            }
        }
        result = conf.get_discord_config()
        assert result.log_channel_id == 999
        assert result.result_channel_id == 888

    @patch.dict("os.environ", {"LOG_CHANNEL_ID": "not-an-int"}, clear=True)
    def test_get_discord_config_invalid_channel_id_env(self):
        """
        環境変数が整数として解釈できない場合は ValueError (握りつぶさない)
        """
        conf = config_module.Config()
        conf.raw_config = {"discord": {}}
        with pytest.raises(ValueError, match="LOG_CHANNEL_ID"):
            conf.get_discord_config()

    @patch.dict("os.environ", {}, clear=True)
    def test_get_discord_config_with_empty_section(self):
        """
        discord セクションが無い場合でも既定値で生成される
        """
        conf = config_module.Config()
        conf.raw_config = {}
        result = conf.get_discord_config()
        assert isinstance(result, DiscordConfig)
        assert result.session_timeout_minutes == 30

    @patch.dict("os.environ", {}, clear=True)
    def test_get_discord_config_invalid(self):
        """
        Discord 設定が不正な場合は ValidationError
        """
        conf = config_module.Config()
        conf.raw_config = {
            "discord": {
                "session_timeout_minutes": 5,
                "warning_minutes_before_end": 10,
            }
        }
        with pytest.raises(ValidationError):
            conf.get_discord_config()

    def test_get_session_config(self):
        """
        get_session_config() が SessionConfig インスタンスを返す
        """
        conf = config_module.Config()
        conf.raw_config = {
            "session": {
                "default_panel_count": 9,
                "allowed_panel_counts": [4, 9, 16, 25],
                "mosaic_levels": {"なし": 300, "強": 45},
            }
        }
        result = conf.get_session_config()
        assert isinstance(result, SessionConfig)
        assert result.default_panel_count == 9
        assert result.mosaic_levels["強"] == 45

    def test_get_session_config_invalid(self):
        """
        セッション設定が不正な場合は ValidationError
        """
        conf = config_module.Config()
        conf.raw_config = {
            "session": {
                "default_panel_count": 9,
                "allowed_panel_counts": [4, 16],
            }
        }
        with pytest.raises(ValidationError):
            conf.get_session_config()

    def test_get_assets_config(self):
        """
        get_assets_config() が AssetsConfig インスタンスを返し、絶対パスに解決される
        """
        conf = config_module.Config()
        conf.raw_config = {
            "assets": {
                "songs_json": "assets/data/all_songs.json",
                "topics_json": "assets/data/all_topics.json",
                "images_dir": "assets/images",
            }
        }
        result = conf.get_assets_config()
        assert isinstance(result, AssetsConfig)
        assert result.songs_json.is_absolute()
        assert result.images_dir.is_absolute()

    def test_get_assets_config_missing_required(self):
        """
        assets セクションが空の場合は ValidationError
        """
        conf = config_module.Config()
        conf.raw_config = {"assets": {}}
        with pytest.raises(ValidationError):
            conf.get_assets_config()


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

    @patch("src.core.config.get_config")
    def test_get_discord_config(self, mock_get_config):
        """
        get_discord_config() が get_config().get_discord_config() を呼ぶ
        """
        from unittest.mock import MagicMock
        mock_conf = MagicMock()
        mock_get_config.return_value = mock_conf

        config_module.get_discord_config("test")
        assert mock_conf.get_discord_config.called

    @patch("src.core.config.get_config")
    def test_get_session_config(self, mock_get_config):
        """
        get_session_config() が get_config().get_session_config() を呼ぶ
        """
        from unittest.mock import MagicMock
        mock_conf = MagicMock()
        mock_get_config.return_value = mock_conf

        config_module.get_session_config("test")
        assert mock_conf.get_session_config.called

    @patch("src.core.config.get_config")
    def test_get_assets_config(self, mock_get_config):
        """
        get_assets_config() が get_config().get_assets_config() を呼ぶ
        """
        from unittest.mock import MagicMock
        mock_conf = MagicMock()
        mock_get_config.return_value = mock_conf

        config_module.get_assets_config("test")
        assert mock_conf.get_assets_config.called
