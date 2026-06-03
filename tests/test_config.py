import pytest

from src.core import config as config_module
from src.core.config import (
    AppEnv,
    BaseAppSettings,
    DevSettings,
    ProdSettings,
    TestSettings,
    get_settings,
)


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    """各テストの実行前に get_settings の lru_cache をクリアする。

    APP_ENV の切り替えがキャッシュに阻まれて反映されない事象を防ぐために使用する。
    """
    get_settings.cache_clear()


def test_test_env_returns_test_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """APP_ENV=test の場合に TestSettings が返ることを確認する。

    Args:
        monkeypatch (pytest.MonkeyPatch): 環境変数を一時的に差し替えるための pytest フィクスチャ。
    """
    monkeypatch.setenv("APP_ENV", "test")
    s = get_settings()
    assert isinstance(s, TestSettings)
    assert s.app_env is AppEnv.TEST
    assert s.log_level == "DEBUG"
    assert s.log_file_name == "test.log"


def test_development_env_returns_dev_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """APP_ENV=development の場合に DevSettings が返ることを確認する。

    Args:
        monkeypatch (pytest.MonkeyPatch): 環境変数を一時的に差し替えるための pytest フィクスチャ。
    """
    monkeypatch.setenv("APP_ENV", "development")
    s = get_settings()
    assert isinstance(s, DevSettings)
    assert s.log_level == "DEBUG"


def test_production_env_returns_prod_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """APP_ENV=production の場合に ProdSettings が返ることを確認する。

    Args:
        monkeypatch (pytest.MonkeyPatch): 環境変数を一時的に差し替えるための pytest フィクスチャ。
    """
    monkeypatch.setenv("APP_ENV", "production")
    s = get_settings()
    assert isinstance(s, ProdSettings)
    assert s.log_level == "INFO"


def test_module_level_settings_is_test_settings() -> None:
    """モジュールロード時に作成される settings がテスト用設定となっていることを確認する。

    conftest.py で APP_ENV=test を設定しているため TestSettings になる想定。
    """
    assert isinstance(config_module.settings, TestSettings)


def test_base_defaults() -> None:
    """BaseAppSettings のログ関連の既定値が想定どおりであることを確認する。"""
    base = BaseAppSettings(app_env=AppEnv.DEVELOPMENT)
    assert base.log_dir == "logs"
    assert base.log_backup_days == 30
