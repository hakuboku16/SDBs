"""
設定ファイルの読み込みと型チェックを行うモジュール

このモジュールはYAMLファイルから設定を読み込み、型安全性を保証します。
"""

import math
import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, field_validator, model_validator

from utils.helpers import get_absolute_path, load_yaml, merge_dicts

_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}

# .env で管理する Discord チャンネル ID の環境変数名
_ENV_LOG_CHANNEL_ID = "LOG_CHANNEL_ID"
_ENV_RESULT_CHANNEL_ID = "RESULT_CHANNEL_ID"


def _read_channel_id_env(name: str) -> Optional[int]:
    """
    環境変数から Discord チャンネル ID を整数として読み込む

    未設定または空文字の場合は None を返します。
    整数として解釈できない値が指定されている場合は意味のあるメッセージで
    ValueError を送出します (要件: エラーは握りつぶさない)。

    Args:
        name: 環境変数名 (例: "LOG_CHANNEL_ID")

    Returns:
        Optional[int]: チャンネル ID。未設定なら None

    Raises:
        ValueError: 値が整数として解釈できない場合
    """
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    try:
        return int(raw.strip())
    except ValueError as e:
        raise ValueError(
            f"環境変数 {name} は整数で指定してください: '{raw}'"
        ) from e


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


class DiscordConfig(BaseModel):
    """
    Discord Bot 動作に必要な設定を包含するモデル

    セッションのタイムアウトや通知先チャンネル ID などを保持します。
    `command_sync_guilds` が空の場合はグローバルにスラッシュコマンドを登録します。
    """

    # 必須項目（既定値あり）
    session_timeout_minutes: int = 30
    warning_minutes_before_end: int = 10

    # オプション項目
    command_sync_guilds: list[int] = []
    log_channel_id: Optional[int] = None
    result_channel_id: Optional[int] = None

    @field_validator("session_timeout_minutes", "warning_minutes_before_end")
    @classmethod
    def must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(f"1以上の整数を指定してください: {v}")
        return v

    @model_validator(mode="after")
    def warning_must_be_less_than_timeout(self) -> "DiscordConfig":
        if self.warning_minutes_before_end >= self.session_timeout_minutes:
            raise ValueError(
                "warning_minutes_before_end は session_timeout_minutes より小さい必要があります "
                f"(warning={self.warning_minutes_before_end}, timeout={self.session_timeout_minutes})"
            )
        return self


class SessionConfig(BaseModel):
    """
    ゲームセッションの進行に関わる設定を包含するモデル

    パネル枚数の選択肢、デフォルト値、モザイクレベル(ラベル→block画素数)を保持します。
    """

    default_panel_count: int = 9
    allowed_panel_counts: list[int] = [4, 9, 16, 25]
    mosaic_levels: dict[str, int] = {
        "なし": 300,
        "弱": 150,
        "中": 90,
        "強": 45,
        "最強": 27,
    }

    @field_validator("allowed_panel_counts")
    @classmethod
    def must_all_be_perfect_squares(cls, v: list[int]) -> list[int]:
        if not v:
            raise ValueError("allowed_panel_counts は空にできません")
        for n in v:
            if n <= 0:
                raise ValueError(f"パネル数は正の整数で指定してください: {n}")
            root = int(math.isqrt(n))
            if root * root != n:
                raise ValueError(f"パネル数は平方数(N×N)で指定してください: {n}")
        return v

    @field_validator("mosaic_levels")
    @classmethod
    def mosaic_block_must_be_positive(cls, v: dict[str, int]) -> dict[str, int]:
        if not v:
            raise ValueError("mosaic_levels は空にできません")
        for label, block in v.items():
            if block <= 0:
                raise ValueError(
                    f"モザイクの block 画素数は正の整数で指定してください: {label}={block}"
                )
        return v

    @model_validator(mode="after")
    def default_must_be_in_allowed(self) -> "SessionConfig":
        if self.default_panel_count not in self.allowed_panel_counts:
            raise ValueError(
                "default_panel_count は allowed_panel_counts に含まれる値である必要があります "
                f"(default={self.default_panel_count}, allowed={self.allowed_panel_counts})"
            )
        return self


class AssetsConfig(BaseModel):
    """
    素材ファイル(楽曲データ・お題定義・楽曲ジャケット画像)のパスを包含するモデル

    YAML 上では相対パスで記述し、読み込み時にプロジェクトルートからの絶対パスに解決します。
    """

    songs_json: Path
    topics_json: Path
    images_dir: Path

    @field_validator("songs_json", "topics_json", "images_dir", mode="before")
    @classmethod
    def resolve_to_absolute(cls, v: object) -> Path:
        if v is None or (isinstance(v, str) and not v.strip()):
            raise ValueError("素材パスは空にできません")
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

    def get_discord_config(self) -> DiscordConfig:
        """
        Discord Bot 設定を取得

        通知先チャンネル ID は .env で管理するため、yaml の値ではなく
        環境変数 (LOG_CHANNEL_ID / RESULT_CHANNEL_ID) から読み込みます。

        Returns:
            DiscordConfig: Discord 関連設定オブジェクト

        Raises:
            pydantic.ValidationError: 設定値が不正な場合
            ValueError: 環境変数が整数として解釈できない場合
        """
        # 環境変数で上書きするため raw_config を破壊しないようコピーする
        discord_config: dict = dict(self.raw_config.get("discord", {}))
        discord_config["log_channel_id"] = _read_channel_id_env(_ENV_LOG_CHANNEL_ID)
        discord_config["result_channel_id"] = _read_channel_id_env(
            _ENV_RESULT_CHANNEL_ID
        )
        return DiscordConfig(**discord_config)

    def get_session_config(self) -> SessionConfig:
        """
        セッション・ゲーム進行設定を取得

        Returns:
            SessionConfig: セッション関連設定オブジェクト

        Raises:
            pydantic.ValidationError: 設定値が不正な場合
        """
        session_config: dict = self.raw_config.get("session", {})
        return SessionConfig(**session_config)

    def get_assets_config(self) -> AssetsConfig:
        """
        素材ファイルパス設定を取得

        Returns:
            AssetsConfig: 素材パス設定オブジェクト

        Raises:
            pydantic.ValidationError: 必須項目が設定されていない場合
        """
        assets_config: dict = self.raw_config.get("assets", {})
        return AssetsConfig(**assets_config)


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


def get_discord_config(environment: Optional[str] = None) -> DiscordConfig:
    """
    Discord Bot 設定を取得

    Args:
        environment: 環境名 (development, production, test)。Noneの場合は現在の環境を使用

    Returns:
        DiscordConfig: Discord 関連設定オブジェクト

    Raises:
        pydantic.ValidationError: 設定値が不正な場合
    """
    return get_config(environment=environment).get_discord_config()


def get_session_config(environment: Optional[str] = None) -> SessionConfig:
    """
    セッション・ゲーム進行設定を取得

    Args:
        environment: 環境名 (development, production, test)。Noneの場合は現在の環境を使用

    Returns:
        SessionConfig: セッション関連設定オブジェクト

    Raises:
        pydantic.ValidationError: 設定値が不正な場合
    """
    return get_config(environment=environment).get_session_config()


def get_assets_config(environment: Optional[str] = None) -> AssetsConfig:
    """
    素材ファイルパス設定を取得

    Args:
        environment: 環境名 (development, production, test)。Noneの場合は現在の環境を使用

    Returns:
        AssetsConfig: 素材パス設定オブジェクト

    Raises:
        pydantic.ValidationError: 必須項目が設定されていない場合
    """
    return get_config(environment=environment).get_assets_config()
