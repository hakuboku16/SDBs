# 開発ガイド

本プロジェクト（Deemo × アタック25 Discord Bot）の開発における標準的なプラクティスを記載しています。

> **設計の単一参照源は [ARCHITECTURE.md](ARCHITECTURE.md) です。**
> 仕様・設計判断・実装ステップは ARCHITECTURE.md を正とし、本ガイドは
> 「どう書くか／どう動かすか」の手順を補足する位置付けです。

## 目次
- [コードの構成](#コードの構成)
- [Cog の追加手順](#cog-の追加手順)
- [サービス層](#サービス層)
- [Cog のテスト](#cog-のテスト)
- [開発時のスラッシュコマンド即時反映](#開発時のスラッシュコマンド即時反映)
- [Docker 開発ワークフロー](#docker-開発ワークフロー)
- [設定管理](#設定管理)
- [ログ出力](#ログ出力)
- [テスト](#テスト)
- [実行](#実行)
- [エラーハンドリング](#エラーハンドリング)
- [パスの操作](#パスの操作)
- [コード品質](#コード品質)

## コードの構成

### `src/`の下層構造

- **`main.py`**: エントリーポイント。`.env` をロードして `SDBsBot.run(token)` を呼び出します。
- **`core/`**: Bot 本体と基盤機能
  - `bot.py`: `SDBsBot`（`commands.Bot` 継承、cog 自動ロード、コマンドツリー同期、`on_app_command_error`）
  - `config.py`: YAML 設定ファイルの読み込みと型安全性を保証（`DiscordConfig` / `SessionConfig` / `AssetsConfig` を含む）
  - `logger.py`: ログのセットアップ
- **`cogs/`**: スラッシュコマンド（**1 コマンド = 1 ファイル**）
  - アンダースコア始まり（例: `_helpers.py`）は cog ローダーの対象外
- **`services/`**: ドメインロジック。原則 Discord 非依存（[サービス層](#サービス層)参照）
- **`utils/`**: プロジェクト全体で共通に利用する関数
  - `helpers.py`: ファイル I/O、データ処理など汎用ヘルパー
  - `validators.py`: バリデーション（`/play` の charming/combo 検証等で利用）

新しいモジュールはプロジェクトの性質に応じて `cogs/`・`services/`・`utils/` のいずれかに追加してください。

## Cog の追加手順

新しいスラッシュコマンドを追加する手順は以下のとおりです。

**1. `src/cogs/<command_name>.py` を作成**

```python
from discord import app_commands
from discord.ext import commands

class MyCommandCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="mycommand", description="...")
    async def mycommand(self, interaction: discord.Interaction) -> None:
        # 通知が必要な場合は self.bot.notifier を使う
        await interaction.response.send_message("ok", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MyCommandCog(bot))
```

**2. 起動するだけで自動ロードされる**

[src/core/bot.py](../src/core/bot.py) の `_load_all_cogs` が `pkgutil.iter_modules` で
`src/cogs/` を走査し、`load_extension` を呼びます。明示登録は不要です。

**注意点**:
- ファイル名がアンダースコア始まり（`_helpers.py` 等）のモジュールは cog 本体ではない
  ヘルパー扱いとして自動ロード対象から除外されます
- `setup` 関数を必ず定義してください（`commands.NoEntryPointError` で除外されます）
- 楽曲名オートコンプリートが必要な場合は [src/cogs/\_helpers.py](../src/cogs/_helpers.py) の
  `build_song_autocomplete(repository)` を利用してください
- スラッシュコマンドツリーは `Bot.setup_hook` で同期されます。開発中の即時反映方法は
  [開発時のスラッシュコマンド即時反映](#開発時のスラッシュコマンド即時反映) を参照

## サービス層

`src/services/` のモジュールは原則 **Discord 非依存** で実装し、cog 側で Discord API
（`Interaction` / `Channel` 等）と橋渡しします。これによりサービスは pytest で純粋関数的に
テストでき、cog テストは Discord 部分を mock するだけで済むようにしています。

| モジュール | 役割 |
| :--- | :--- |
| [`session.py`](../src/services/session.py) | `Session` / `PlayRecord` のデータモデル |
| [`session_manager.py`](../src/services/session_manager.py) | シングルトン。同時 1 セッション保証、警告/タイムアウトのタイマー（`asyncio.create_task`）を保持 |
| [`session_finalizer.py`](../src/services/session_finalizer.py) | `/end`（手動）と自動タイムアウトの**共通終了処理**。`SessionManager.is_active()` で冪等性を担保 |
| [`task.py`](../src/services/task.py) | `Task` モデル（type / set_value / value / current / cleared） |
| [`task_generator.py`](../src/services/task_generator.py) | `all_topics.json` から N 個ランダム生成 |
| [`task_evaluator.py`](../src/services/task_evaluator.py) | type ごとの評価関数を辞書登録（**戦略パターン**）。`PlayRecord` を全タスクで評価 |
| [`song_repository.py`](../src/services/song_repository.py) | `all_songs.json` のロード、部分一致検索、楽曲名 → 画像パス解決 |
| [`image_processor.py`](../src/services/image_processor.py) | Pillow でパネル合成・回転・グレースケール・モザイク |
| [`discord_notifier.py`](../src/services/discord_notifier.py) | ログチャンネル / 結果チャンネルへの送信 |

`SessionManager` のタイマー遅延値は呼び出し側 cog で `DiscordConfig` から算出して
`start()` に注入します（manager 自身は config に依存しない設計）。

## Cog のテスト

cog テストは [tests/cogs/conftest.py](../tests/cogs/conftest.py) で提供される
`Interaction` mock ヘルパーを利用します。
`response.send_message` / `followup.send` / `user` / `channel` / `guild` の最低限の振る舞いが
mock 化されているので、cog の振る舞いを以下のように検証できます。

```python
@pytest.mark.asyncio
async def test_my_command(make_interaction):
    interaction = make_interaction()
    cog = MyCommandCog(bot=mock.MagicMock())
    await cog.mycommand.callback(cog, interaction)
    interaction.response.send_message.assert_called_once_with("ok", ephemeral=True)
```

`SessionManager` はシングルトンなので、テスト間で状態が漏れないように `end()` / `reset()` を
fixture の teardown で呼ぶか、`SessionManager._current = None` で明示的にリセットしてください。

## 開発時のスラッシュコマンド即時反映

`Bot.setup_hook` の `_sync_command_tree` は以下のように動作します。

| `discord.command_sync_guilds` | 同期先 | 反映タイミング |
| :--- | :--- | :--- |
| 空（既定） | グローバル | 最大 1 時間程度 |
| Guild ID 配列 | 各 Guild へ即時同期 | 数秒以内 |

開発中は [config/settings.development.yaml](../config/settings.development.yaml) に
以下を追加すると即時反映されます。

```yaml
discord:
  command_sync_guilds:
    - 123456789012345678   # 開発用サーバーの Guild ID
```

本番環境（`ENVIRONMENT=production`）では `command_sync_guilds` を空のままにし、グローバル登録してください。

## Docker 開発ワークフロー

24h 稼働を想定した [Dockerfile](../Dockerfile) と [docker-compose.yml](../docker-compose.yml) を用意しています。

```bash
# ビルド + 起動（バックグラウンド）
docker compose up --build -d

# ログ追従
docker compose logs -f

# 停止
docker compose down

# 再ビルドなしで再起動（コード変更を反映する場合は --build を付ける）
docker compose restart
```

**ボリュームマウント**:
- `./logs:/app/logs` — ログをホスト側で永続化（`docker logs` 経由でなくファイルでも閲覧可能）
- `./assets:/app/assets` — 楽曲データやジャケット画像を再ビルドなしで差し替え可能

**設計上の注意**:
- `restart: always` により、コンテナが落ちた場合も自動復旧します
- 非 root ユーザー（`app`）で実行されるため、ホストでマウントしたディレクトリの
  書き込み権限に注意してください
- `.env` から `DISCORD_TOKEN` を注入します。コンテナ内に直接埋め込まない設計です

## 設定管理

### 設定の管理方針

| 種別                                       | 管理場所             | 例                                        |
| :----------------------------------------- | :------------------- | :---------------------------------------- |
| アプリケーションの挙動 (タイムアウト等)    | `config/*.yaml`      | `discord.session_timeout_minutes`         |
| 機密情報・環境固有の ID                    | `.env`               | `DISCORD_TOKEN` / `LOG_CHANNEL_ID` / `RESULT_CHANNEL_ID` |

通知先チャンネル ID は環境ごとにサーバー構成が変わる前提のため、yaml ではなく `.env` で
管理します。`get_discord_config()` が起動時に環境変数を読み込んで `DiscordConfig` に
注入します (整数として解釈できない値が指定された場合は `ValueError` を送出)。

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
from src.core.config import (
    get_config,
    get_discord_config,
    get_session_config,
    get_assets_config,
)

config = get_config()
print(config.project_name)          # プロジェクト名
print(config.get_log_path())        # ログディレクトリの絶対パス

# Bot 関連の型付き設定
discord_config = get_discord_config()
print(discord_config.session_timeout_minutes)   # 30
print(discord_config.command_sync_guilds)       # list[int]

session_config = get_session_config()
print(session_config.allowed_panel_counts)      # [4, 9, 16, 25]
print(session_config.mosaic_levels["中"])       # 90
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

