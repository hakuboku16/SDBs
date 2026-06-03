from enum import Enum
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnv(str, Enum):
    """アプリケーションの実行環境を表す列挙型。"""

    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class BaseAppSettings(BaseSettings):
    """アプリ全体で共有する設定の基底クラス。

    環境変数および .env ファイルからログ関連の既定値を読み込む。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: AppEnv = AppEnv.DEVELOPMENT
    log_level: str = "INFO"
    log_dir: str = "logs"
    log_file_name: str = "python.log"
    log_backup_days: int = 30


class DevSettings(BaseAppSettings):
    """開発環境向けの設定。

    デバッグ情報を確認できるようログレベルを DEBUG に上書きする。
    """

    log_level: str = "DEBUG"


class TestSettings(BaseAppSettings):
    """テスト環境向けの設定。

    テスト専用のログファイル名と DEBUG レベルを利用する。
    """

    # クラス名が "Test" で始まるため pytest が誤ってテストクラスとして
    # 収集しようとするのを抑止する。
    __test__ = False

    log_level: str = "DEBUG"
    log_file_name: str = "test.log"


class ProdSettings(BaseAppSettings):
    """本番環境向けの設定。"""

    # 基底クラスの既定値と同値だが、本番のログレベルを明示するため意図的に再宣言する。
    log_level: str = "INFO"


_SETTINGS_BY_ENV: dict[AppEnv, type[BaseAppSettings]] = {
    AppEnv.DEVELOPMENT: DevSettings,
    AppEnv.TEST: TestSettings,
    AppEnv.PRODUCTION: ProdSettings,
}


@lru_cache
def get_settings() -> BaseAppSettings:
    """現在の APP_ENV に対応する設定インスタンスを返す。

    結果は lru_cache によりキャッシュされ、プロセス内で同一インスタンスを返す。

    Returns:
        BaseAppSettings: 実行環境に応じた設定オブジェクト。
    """
    env = BaseAppSettings().app_env
    return _SETTINGS_BY_ENV[env]()


settings = get_settings()
