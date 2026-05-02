# 開発ガイド

このプロジェクトテンプレートを使用した開発における標準的なプラクティスを記載しています。

## コードの構成

### `src/`の下層構造

- **`main.py`**: アプリケーションのエントリーポイント。ここから処理を開始します。
- **`core/`**: 設定とログ管理などの基盤機能
  - `config.py`: YAML設定ファイルの読み込みと型安全性を保証
  - `logger.py`: ログの設定とセットアップ
- **`utils/`**: プロジェクト全体で共通に利用する関数
  - `helpers.py`: ファイルI/O、データ処理など汎用ヘルパー関数
  - `validators.py`: データバリデーション関数

新しいモジュールはプロジェクトの性質に応じて`src/`直下、または`utils/`に追加してください。

## 設定管理

### 環境別設定の使い分け

設定は環境ごとに異なる値をオーバーライドする設計になっています：

| 環境   | ファイル                           | 用途                 |
| ------ | ---------------------------------- | -------------------- |
| 共通   | `config/settings.yaml`             | 全環境で共通する設定 |
| 開発   | `config/settings.development.yaml` | ローカル開発環境     |
| 本番   | `config/settings.production.yaml`  | 本番環境             |
| テスト | `config/settings.test.yaml`        | テスト実行時         |

### 設定へのアクセス

```python
from core.config import get_config

config = get_config()

# 設定値へのアクセス
print(config.project.name)      # プロジェクト名
print(config.app.timeout)       # タイムアウト値
print(config.get_log_path())    # ログディレクトリの絶対パス
```

## ログ出力

### ロガーの初期化

```python
from core.logger import setup_logger
from core.config import get_config

config = get_config()
logger = setup_logger(name="my_module", config=config)

logger.debug("デバッグ情報")
logger.info("一般情報")
logger.warning("警告")
logger.error("エラー", exc_info=True)
```

### ログレベルの設定

ログレベルは環境ごとに最適化されています：

| 環境       | コンソール | ファイル | 目的                                                   |
| ---------- | ---------- | -------- | ------------------------------------------------------ |
| **開発**   | DEBUG      | DEBUG    | 開発中のデバッグ。全ログを確認可能                     |
| **テスト** | INFO       | DEBUG    | テスト結果は本番に近い条件。失敗時はファイルで詳細確認 |
| **本番**   | WARNING    | INFO     | コンソール出力最小化。ファイルに運用情報を記録         |

## テスト

### テストの構成

テストは`tests/`フォルダに配置します。`conftest.py`では共通のfixture を定義しています：

```python
# tests/conftest.py で定義されたfixture の使用例
def test_something(test_config, test_data_dir):
    """テスト用設定とテストデータディレクトリを利用"""
    assert test_config.environment == "test"
    assert test_data_dir.exists()
```

### テストの実行

```bash
# 全テストを実行
pytest

# 特定のテストファイルを実行
pytest tests/test_config.py

# 特定のテストクラス・メソッドを実行
pytest tests/test_config.py::TestConfigLoading::test_load_development_config

# カバレッジ付きで実行
pytest --cov=src tests/

# ログ出力付きで実行（詳細）
pytest -v -s tests/
```

## 実行

### 実行方法

```bash
# エントリーポイント（main.py）から実行
python src/main.py

# またはプロジェクトルートをPYTHONPATHに指定
PYTHONPATH=. python src/main.py

# テスト実行
pytest
```

## エラーハンドリング

### 推奨パターン

```python
from core.logger import setup_logger

logger = setup_logger(__name__)

try:
    # メイン処理
    result = some_function()
except ValueError as e:
    logger.error(f"入力値が不正です: {e}")
    raise
except Exception as e:
    logger.error(f"予期しないエラーが発生しました: {e}", exc_info=True)
    raise
finally:
    logger.info("処理を終了します")
```

## パスの操作

### 推奨される相対パスの解決方法

```python
from core.config import get_config

config = get_config()

# プロジェクトルートからの相対パス
data_file = config.get_data_path() / "input.csv"
output_file = config.get_output_path() / "result.json"

# カスタムパス
custom_path = config.get_absolute_path("custom/folder/file.txt")
```

## コード品質

### 型ヒント

Pylanceによる型チェックをサポートするため、関数には型ヒントを付与してください：

```python
from typing import Optional, List
from pathlib import Path

def process_file(input_path: Path, output_dir: Path) -> Optional[dict]:
    """ファイルを処理する"""
    pass
```

### ドキュメンテーション

モジュール、クラス、関数には必ずdocstringを付与してください：

```python
def validate_email(email: str) -> bool:
    """
    メールアドレスの妥当性をチェック

    Args:
        email: チェック対象のメールアドレス

    Returns:
        有効な形式の場合True

    Raises:
        TypeError: email が文字列でない場合
    """
    pass
```

