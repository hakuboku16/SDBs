"""
設定ファイルの読み込みと型チェックを行うモジュール

このモジュールはYAMLファイルから設定を読み込み、型安全性を保証します。
"""

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, field_validator

from utils.helpers import get_absolute_path, load_yaml, merge_dicts

_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


# ==================================================
# データ格納用クラス
# ==================================================
class LoggerConfig(BaseModel):
    """
    ログ出力に必要な設定を包含するモデル

    src/core/logger.py が必要とするすべての情報を提供します。
    必須項目（console_level, file_level, format）が未設定または空文字列の場合、
    ValidationError を送出します。
    """

    # 必須項目
    console_level: str
    file_level: str
    format: str

    # オプション項目
    log_dir: Path = Path("logs")
    log_file: str = "python.log"
    max_bytes: int = 10485760  # 10MB
    backup_count: int = 5

    @field_validator("console_level", "file_level")
    @classmethod
    def must_be_valid_level(cls, v: str) -> str:
        upper = v.strip().upper()
        if upper not in _VALID_LOG_LEVELS:
            raise ValueError(
                f"無効なログレベル: '{v}'. 有効な値: {', '.join(sorted(_VALID_LOG_LEVELS))}"
            )
        return upper

    @field_validator("format")
    @classmethod
    def must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("空文字列は設定できません")
        return v

    @field_validator("log_dir", mode="before")
    @classmethod
    def resolve_log_dir(cls, v: object) -> Path:
        return get_absolute_path(str(v))


# ==================================================
# 設定値の読み込み
# ==================================================
class Config:
    """
    設定管理クラス

    YAML ファイルから設定を読み込み、型安全なアクセスを提供します。
    環境ごとに異なる設定ファイルを読み込むことができます。
    シングルトンパターンで環境ごとのインスタンスをキャッシュします。
    """

    # クラス変数：シングルトンパターンのキャッシュ
    _instances: dict[str, "Config"] = {}

    def __init__(
        self, environment: str = "development", config_path: Optional[Path] = None
    ):
        """
        設定を初期化します

        Args:
            environment (str, optional): 環境名 (development, production, test)。
            config_path (Optional[Path], optional): 設定ファイルのパス。Noneの場合はデフォルトパスを使用
        """

        # 基本設定ファイルを取得
        if config_path is None:
            config_path = get_absolute_path("config/settings.yaml")
        self.raw_config = load_yaml(config_path)

        # 環境別設定ファイルを読み込んでマージ
        env_config_path = get_absolute_path(f"config/settings.{environment}.yaml")
        if env_config_path.exists():
            env_config = load_yaml(env_config_path)
            self.raw_config = merge_dicts(self.raw_config, env_config)

    @classmethod
    def get(cls, environment: str = "development") -> "Config":
        """
        設定インスタンスを取得（環境ごとのキャッシュ）

        Args:
            environment: 環境名 (development, production, test)

        Returns:
            Config: 設定オブジェクト
        """
        if environment not in cls._instances:
            cls._instances[environment] = cls(environment=environment)
        return cls._instances[environment]

    @classmethod
    def reset(cls, environment: Optional[str] = None) -> None:
        """
        キャッシュをリセット（テスト用）

        Args:
            environment: リセット対象の環境。Noneの場合はすべてリセット
        """
        if environment is None:
            cls._instances.clear()
        else:
            cls._instances.pop(environment, None)

    def get_logger_config(self) -> LoggerConfig:
        """
        ロガー設定を取得

        logger.py が必要とするすべての設定情報を提供します。
        必須項目が欠落している場合は ValidationError を発生させます。

        Returns:
            LoggerConfig: ロガー設定オブジェクト

        Raises:
            pydantic.ValidationError: 必須項目が設定されていない場合
        """
        logger_config: dict = self.raw_config.get("logger", {})
        return LoggerConfig(**logger_config)


# ==================================================
# グローバル環境管理
# ==================================================

# アプリケーション全体で使用する環境
_current_environment: str = "development"


def set_environment(environment: str) -> None:
    """
    アプリケーション全体で使用する環境を設定

    main.py の起動時に環境を1度だけ設定します。
    その後、すべての get_*_config() はこの環境を使用します。

    Args:
        environment: 環境名 (development, production, test)
    """
    global _current_environment
    _current_environment = environment


def _get_current_environment() -> str:
    """
    現在設定されている環境を取得

    Returns:
        str: 現在の環境名
    """
    return _current_environment


# ==================================================
# ヘルパー関数
# ==================================================
def get_config(environment: Optional[str] = None) -> Config:
    """
    設定インスタンスを取得（環境ごとのキャッシュ）

    環境を省略した場合は set_environment() で設定した環境を使用します。
    Config クラスのシングルトン機能をラップしています。

    Args:
        environment: 環境名 (development, production, test)。Noneの場合は現在の環境を使用

    Returns:
        Config: 設定オブジェクト
    """
    if environment is None:
        environment = _get_current_environment()
    return Config.get(environment)


def get_logger_config(environment: Optional[str] = None) -> LoggerConfig:
    """
    ロガー設定を取得

    環境を省略した場合は set_environment() で設定した環境を使用します。

    Args:
        environment: 環境名 (development, production, test)。Noneの場合は現在の環境を使用

    Returns:
        LoggerConfig: ロガー設定オブジェクト

    Raises:
        pydantic.ValidationError: 必須項目が設定されていない場合
    """
    return get_config(environment=environment).get_logger_config()
