"""
pytest の設定ファイル

テスト全体で共通する fixture や設定をここに定義します。
"""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml

from src.core.config import Config, set_environment
from src.services.task import PlayQuality, Task


# ==================================================
# テスト用 Task ファクトリ
# ==================================================
def make_task(
    *,
    type: str,
    set_value: int,
    value: Any = None,
    play_quality: PlayQuality = "プレイ",
    description_template: str = "",
    current: int = 0,
    cleared: bool = False,
) -> Task:
    """
    テスト用に `Task` を簡潔に生成するファクトリ関数

    新規追加された ``play_quality`` / ``description_template`` にデフォルト値を
    与え、既存テストを最小変更で動かせるようにします。AC/FC のような
    play_quality 関連テストでは明示的に上書きしてください。
    """
    return Task(
        type=type,
        set_value=set_value,
        value=value,
        play_quality=play_quality,
        description_template=description_template,
        current=current,
        cleared=cleared,
    )


# ==================================================
# 以下、全テストで自動実行される fixture
# ==================================================
@pytest.fixture(autouse=True)
def reset_config_cache():
    """
    各テスト後に Config のキャッシュをリセットする autouse fixture

    テスト間の状態汚染を防ぐため、各テスト実行後に
    シングルトンキャッシュをクリアして環境をリセットします。
    """
    yield
    Config.reset()
    set_environment("development")


# ==================================================
# 以下、全テスト共通の fixture
# ==================================================
@pytest.fixture
def test_base_dir() -> Path:
    """
    テスト用プロジェクト基底パスを提供する fixture
    tests/ から1階層上

    Returns:
        Path: プロジェクトの基底パス
    """
    return Path(__file__).parent.parent


@pytest.fixture
def valid_yaml_file(tmp_path) -> Path:
    """
    有効なYAMLデータを一時ファイルとして作成し、そのパスを返すfixture
    """
    data = {
        "project_name": "template",
        "logger": {"console_level": "DEBUG", "file_level": "DEBUG"},
    }
    yaml_path = tmp_path / "valid.yaml"
    yaml_path.write_text(yaml.dump(data), encoding="utf-8")
    return yaml_path


@pytest.fixture
def mock_logger_config(tmp_path) -> MagicMock:
    """
    logger設定のモックオブジェクトを作成するfixture

    Args:
        tmp_path: pytest が提供する一時ディレクトリ

    Returns:
        MagicMock: ロガー設定のモックオブジェクト
    """
    mock_config = MagicMock()
    mock_config.console_level = "DEBUG"
    mock_config.file_level = "DEBUG"
    mock_config.format = "[%(asctime)s] %(levelname)s: %(message)s"
    mock_config.log_dir = tmp_path
    mock_config.log_file = "python.log"
    mock_config.max_bytes = 10485760
    mock_config.backup_count = 5
    return mock_config
