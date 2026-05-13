# 開発ガイド

本プロジェクト (Deemo × アタック25 Discord Bot) を**ローカル環境で導入し開発する**ための
手順をまとめたガイドです。Bot の遊び方を知りたい方は [README.md](../README.md) を、
設計判断や全体像を知りたい方は [ARCHITECTURE.md](ARCHITECTURE.md) を参照してください。

> **設計の単一参照源は [ARCHITECTURE.md](ARCHITECTURE.md) です。**
> 仕様・設計判断・実装ステップは ARCHITECTURE.md を正とし、本ガイドは
> 「どう書くか / どう動かすか」の手順を補足する位置付けです。

## 目次

- [動作要件](#動作要件)
- [セットアップ](#セットアップ)
- [実行方法](#実行方法)
  - [ローカル実行](#ローカル実行)
  - [Docker 実行 (推奨・24h 稼働)](#docker-実行-推奨24h-稼働)
- [環境変数](#環境変数)
- [設定ファイル](#設定ファイル)
- [テストの実行](#テストの実行)
- [開発時のスラッシュコマンド即時反映](#開発時のスラッシュコマンド即時反映)
- [プロジェクト構成](#プロジェクト構成)
- [コードの構成](#コードの構成)
- [Cog の追加手順](#cog-の追加手順)
- [サービス層](#サービス層)
- [Cog のテスト](#cog-のテスト)
- [ログ出力](#ログ出力)
- [エラーハンドリング](#エラーハンドリング)
- [パスの操作](#パスの操作)
- [コード品質](#コード品質)


## 動作要件

| 項目                                                                       | バージョン       | 用途                                         |
| :------------------------------------------------------------------------- | :--------------- | :------------------------------------------- |
| Windows 11 Home                                                            | 25H2 で動作確認  | 開発機 OS (他 OS でも動作する想定)           |
| [Python](https://www.python.org/downloads/)                                | 3.13.4           | ローカル実行時のみ必須 (Docker 利用時は不要) |
| [Docker Desktop](https://www.docker.com/products/docker-desktop/)          | 任意             | 本番運用 (24h 稼働) に推奨                   |
| [VSCode](https://code.visualstudio.com/)                                   | 1.101.0 で動作確認 | 開発エディタ (任意)                          |

主要な Python パッケージは [requirements.txt](../requirements.txt) を参照してください
(主なもの: `discord.py>=2.4`、`Pillow>=10`、`pydantic==2.12.5`、`python-dotenv`、`PyYAML`、
`pytest`、`pytest-cov`)。


## セットアップ

**1. リポジトリの取得**

```bash
git clone <gitのURL>
cd SDBs
```

**2. Discord Bot トークンの取得**

[Discord Developer Portal](https://discord.com/developers/applications) でアプリケーションを
作成し、Bot トークンを発行してください。Bot は最低限 `applications.commands` スコープで
サーバーに招待します。

**3. 環境変数の設定**

```bash
copy .env.example .env
```

`.env` を開き、最低でも `DISCORD_TOKEN` に発行済みトークンを設定します。
ログ送信先 / 結果送信先のチャンネル ID もここで設定します (詳細は[環境変数](#環境変数))。

**4. ローカル実行する場合のみ: 仮想環境と依存パッケージ**

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Docker で実行する場合は本ステップは不要です。


## 実行方法

### ローカル実行

```bash
.venv\Scripts\activate
python src/main.py
```

CLI 引数 `--env` または環境変数 `ENVIRONMENT` で実行環境を上書きできます
(`development` / `production` / `test`)。

### Docker 実行 (推奨・24h 稼働)

```bash
# 起動 (バックグラウンド)
docker compose up --build -d

# ログ追従
docker compose logs -f

# 停止
docker compose down

# 再ビルドなしで再起動 (コード変更を反映する場合は --build を付ける)
docker compose restart
```

[Dockerfile](../Dockerfile) は `python:3.13-slim` ベースで、非 root ユーザー `app` で
Bot を起動します。[docker-compose.yml](../docker-compose.yml) では以下を行っています。

- `restart: always` — コンテナ落ちでも自動復旧
- `env_file: .env` — `DISCORD_TOKEN` 等を `.env` から注入 (イメージに埋め込まない)
- ボリュームマウント:
  - `./logs:/app/logs` — ログをホスト側で永続化
  - `./assets:/app/assets` — 楽曲データ / ジャケット画像を再ビルドなしで差し替え可能
- `healthcheck` — Python プロセスの生存を定期的にチェック


## 環境変数

`.env.example` をコピーして `.env` を作成し、以下を設定してください。

| 変数                | 必須 | 説明                                                                       |
| :------------------ | :--: | :------------------------------------------------------------------------- |
| `DISCORD_TOKEN`     |  ◯   | Discord Bot トークン                                                       |
| `ENVIRONMENT`       |      | 実行環境 (`development` / `production` / `test`)。既定は `development`     |
| `LOG_CHANNEL_ID`    |      | エラーログ送信先の Discord チャンネル ID。未設定なら送信スキップ           |
| `RESULT_CHANNEL_ID` |      | セッション終了時の結果送信先チャンネル ID。未設定なら送信スキップ          |

`LOG_CHANNEL_ID` / `RESULT_CHANNEL_ID` は整数として解釈できる値である必要があります
(空文字や `None` は未設定扱い、整数化できない値は起動時に `ValueError`)。


## 設定ファイル

[config/](../config/) 配下の YAML で挙動を制御します。`settings.yaml` が共通設定で、
環境別ファイルが値を上書きします (`merge_dicts` で再帰的にマージ)。

| ファイル                                                                | 用途                                  |
| :---------------------------------------------------------------------- | :------------------------------------ |
| [config/settings.yaml](../config/settings.yaml)                         | 共通設定                              |
| [config/settings.development.yaml](../config/settings.development.yaml) | 開発環境 (ログレベル等)               |
| [config/settings.production.yaml](../config/settings.production.yaml)   | 本番環境 (ログレベル等)               |
| [config/settings.test.yaml](../config/settings.test.yaml)               | テスト用                              |

主な Bot 関連項目 ([config/settings.yaml](../config/settings.yaml)):

| キー                                  | 説明                                                          |
| :------------------------------------ | :------------------------------------------------------------ |
| `discord.command_sync_guilds`         | 開発時の即時反映用 Guild ID 配列。本番は空でグローバル登録    |
| `discord.session_timeout_minutes`     | セッション制限時間 (分)。既定 `30`                            |
| `discord.warning_minutes_before_end`  | 終了前の警告通知タイミング (分)。既定 `10`                    |
| `session.default_panel_count`         | パネル枚数の既定値 (`9`)                                      |
| `session.allowed_panel_counts`        | 選択可能なパネル枚数 (`[4, 9, 16, 25]`)                       |
| `session.mosaic_levels`               | モザイク強度ラベル → ブロック画素数の対応                     |
| `assets.songs_json`                   | 楽曲メタデータ JSON へのパス                                  |
| `assets.topics_json`                  | お題定義 JSON へのパス                                        |
| `assets.images_dir`                   | 楽曲ジャケット画像ディレクトリ                                |

> **チャンネル ID** (ログ送信先 / 結果送信先) は yaml ではなく `.env` で管理します
> (`LOG_CHANNEL_ID` / `RESULT_CHANNEL_ID`)。詳細は [環境変数](#環境変数) を参照してください。


## テストの実行

```bash
# 全テスト
pytest

# 特定モジュール
pytest tests/cogs/test_start_session.py

# 特定のテストクラス・メソッドを実行
pytest tests/services/test_task_evaluator.py::TestTaskEvaluator::test_evaluate_title_include

# カバレッジ付き
pytest --cov=src

# ログ出力付き (詳細)
pytest -v -s
```

[pytest.ini](../pytest.ini) で `--cov=src` がデフォルト設定されています。
テストは [`tests/`](../tests/) 配下に `src/` と対称な構成で配置しており、
`tests/conftest.py` で `test_config` 等の共通 fixture を提供しています。


## 開発時のスラッシュコマンド即時反映

`SDBsBot.setup_hook` の `_sync_command_tree` ([src/core/bot.py](../src/core/bot.py)) は
以下のように動作します。

| `discord.command_sync_guilds` | 同期先                | 反映タイミング |
| :---------------------------- | :-------------------- | :------------- |
| 空 (既定)                     | グローバル            | 最大 1 時間程度 |
| Guild ID 配列                 | 各 Guild へ即時同期    | 数秒以内       |

開発中は [config/settings.development.yaml](../config/settings.development.yaml) に
以下を追加すると即時反映されます。

```yaml
discord:
  command_sync_guilds:
    - 123456789012345678   # 開発用サーバーの Guild ID
```

本番環境 (`ENVIRONMENT=production`) では `command_sync_guilds` を空のままにし、
グローバル登録してください。

PowerShell から都度環境を切り替えて起動する場合は次のように指定できます。

```powershell
$env:ENVIRONMENT='test'; python src/main.py
$env:ENVIRONMENT='production'; python src/main.py
```


## プロジェクト構成

```
.
├── assets/                       # 楽曲データ・お題定義・ジャケット画像
│   ├── data/
│   │   ├── all_songs.json        # 楽曲メタデータ
│   │   └── all_topics.json       # お題定義
│   └── images/                   # 楽曲ジャケット画像 (300×300 RGB)
├── config/                       # 設定ファイル (共通 + 環境別オーバーライド)
├── docs/
│   ├── ARCHITECTURE.md           # 設計の単一参照源
│   └── DEVELOPMENT.md            # 本ガイド
├── logs/                         # ログ出力先 (Docker でホストマウント)
├── src/
│   ├── main.py                   # エントリーポイント (Bot 起動)
│   ├── core/
│   │   ├── bot.py                # SDBsBot (cog 自動ロード・コマンド同期・エラーハンドラ)
│   │   ├── config.py             # YAML 設定 + Pydantic モデル
│   │   └── logger.py             # ログ管理
│   ├── cogs/                     # スラッシュコマンド (1 コマンド = 1 ファイル)
│   │   ├── _helpers.py           # 楽曲名オートコンプリート / embed ビルダ等の共通関数
│   │   ├── start_session.py      # /start
│   │   ├── end_session.py        # /end
│   │   ├── reset_session.py      # /reset
│   │   ├── input_play.py         # /play
│   │   ├── answer_song.py        # /answer
│   │   └── show_progress.py      # /progress
│   ├── services/                 # ドメインロジック (Discord 非依存が原則)
│   │   ├── session.py            # Session / PlayRecord / AnswerRecord
│   │   ├── session_manager.py    # シングルトン + タイマー (asyncio.create_task)
│   │   ├── session_finalizer.py  # /end と自動タイムアウトの共通終了処理
│   │   ├── task.py               # Task モデル (play_quality / set_value / value)
│   │   ├── task_generator.py     # all_topics.json から N 個ランダム生成
│   │   ├── task_evaluator.py     # type ごとの評価関数 (戦略パターン)
│   │   ├── song_repository.py    # all_songs.json ロード + 部分一致検索
│   │   ├── image_processor.py    # Pillow でパネル合成・回転・グレースケール・モザイク
│   │   └── discord_notifier.py   # ログ / 結果チャンネルへの送信
│   └── utils/
│       ├── helpers.py            # ファイル I/O 等
│       └── validators.py         # バリデーション関数
├── tests/                        # pytest テスト (src と対称な構成)
├── .env.example                  # 環境変数テンプレート
├── Dockerfile                    # python:3.13-slim ベース、非 root 実行
├── docker-compose.yml            # 24h 稼働、./logs ./assets をマウント
├── pytest.ini                    # pytest 設定 (--cov=src)
├── requirements.txt              # 依存ライブラリ
└── README.md                     # プレイヤー向け概要
```


## コードの構成

### `src/` の下層構造

- **`main.py`**: エントリーポイント。`.env` をロードして `SDBsBot.run(token)` を呼び出します。
- **`core/`**: Bot 本体と基盤機能
  - `bot.py`: `SDBsBot` (`commands.Bot` 継承、cog 自動ロード、コマンドツリー同期、
    `on_app_command_error` でログチャンネル通知 + ユーザーへ embed 応答)
  - `config.py`: YAML 設定ファイルの読み込みと型安全性を保証
    (`DiscordConfig` / `SessionConfig` / `AssetsConfig` / `LoggerConfig` を含む)
  - `logger.py`: ログのセットアップ
- **`cogs/`**: スラッシュコマンド (**1 コマンド = 1 ファイル**)
  - アンダースコア始まり (例: `_helpers.py`) は cog ローダーの対象外
  - `_helpers.py` には楽曲名オートコンプリート、用途別 embed ビルダ
    (`build_info_embed` / `build_success_embed` / `build_warning_embed` / `build_error_embed`)、
    お題 1 件を field に整形する `build_topic_field` を集約
- **`services/`**: ドメインロジック。原則 Discord 非依存 ([サービス層](#サービス層) 参照)
- **`utils/`**: プロジェクト全体で共通に利用する関数
  - `helpers.py`: ファイル I/O、データ処理など汎用ヘルパー
  - `validators.py`: バリデーション (`/play` の charming/combo 自然数チェック等で利用)

新しいモジュールはプロジェクトの性質に応じて `cogs/` / `services/` / `utils/` のいずれかに
追加してください。


## Cog の追加手順

新しいスラッシュコマンドを追加する手順は以下のとおりです。

**1. `src/cogs/<command_name>.py` を作成**

```python
import discord
from discord import app_commands
from discord.ext import commands

from src.cogs._helpers import build_error_embed, build_success_embed


class MyCommandCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        super().__init__()
        self.bot = bot

    @app_commands.command(name="mycommand", description="...")
    async def mycommand(self, interaction: discord.Interaction) -> None:
        # Bot が送るメッセージは embed 形式に統一する
        await interaction.response.send_message(
            embed=build_success_embed("ok"), ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MyCommandCog(bot))
```

**2. 起動するだけで自動ロードされる**

[src/core/bot.py](../src/core/bot.py) の `_load_all_cogs` が `pkgutil.iter_modules` で
`src/cogs/` を走査し、`load_extension` を呼びます。明示登録は不要です。

**注意点**:

- ファイル名がアンダースコア始まり (`_helpers.py` 等) のモジュールは cog 本体ではない
  ヘルパー扱いとして自動ロード対象から除外されます
- `setup` 関数を必ず定義してください (定義漏れは `commands.NoEntryPointError` で
  warning ログに残り、対象 cog はスキップされますが他 cog のロードは継続します)
- 楽曲名オートコンプリートが必要な場合は [src/cogs/\_helpers.py](../src/cogs/_helpers.py) の
  `build_song_autocomplete(repository)` を利用してください
- Bot から送るメッセージはすべて embed 形式に統一しています。色分けが必要な場合は
  `build_info_embed` / `build_success_embed` / `build_warning_embed` / `build_error_embed`
  を使い分けてください
- スラッシュコマンドツリーは `Bot.setup_hook` で同期されます。開発中の即時反映方法は
  [開発時のスラッシュコマンド即時反映](#開発時のスラッシュコマンド即時反映) を参照


## サービス層

`src/services/` のモジュールは原則 **Discord 非依存** で実装し、cog 側で Discord API
(`Interaction` / `Channel` 等) と橋渡しします。これによりサービスは pytest で純粋関数的に
テストでき、cog テストは Discord 部分を mock するだけで済むようにしています。

| モジュール                                                                  | 役割                                                                                                                                  |
| :-------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------ |
| [`session.py`](../src/services/session.py)                                  | `Session` / `PlayRecord` / `AnswerRecord` のデータモデル。`rotation_angle` でセッション中の回転角度を固定保持             |
| [`session_manager.py`](../src/services/session_manager.py)                  | シングルトン。同時 1 セッション保証、警告 / タイムアウトのタイマー (`asyncio.create_task`) を保持                                     |
| [`session_finalizer.py`](../src/services/session_finalizer.py)              | `/end` (手動) と自動タイムアウトの **共通終了処理**。`SessionManager.is_active()` で冪等性を担保。楽曲名はスポイラー形式で結果通知 |
| [`task.py`](../src/services/task.py)                                        | `Task` モデル (`type` / `set_value` / `value` / `play_quality` / `description_template` / `current` / `cleared`)。`format_description` で placeholder 置換 |
| [`task_generator.py`](../src/services/task_generator.py)                    | `all_topics.json` から N 個ランダム生成。`play_quality` は AC=1 / FC=3 / プレイ=6 の重み付き抽選                                       |
| [`task_evaluator.py`](../src/services/task_evaluator.py)                    | type ごとの評価関数を辞書登録 (**戦略パターン**)。`PlayRecord` を全タスクで評価し、`_satisfies_quality` で品質フィルタも担う           |
| [`song_repository.py`](../src/services/song_repository.py)                  | `all_songs.json` のロード、部分一致検索 (大文字小文字無視)、楽曲名 → 画像パス解決                                                     |
| [`image_processor.py`](../src/services/image_processor.py)                  | Pillow でパネル合成・回転・グレースケール・モザイク。`pick_rotation_angle` で角度決定、`compose` に `rotation_angle` を注入する設計     |
| [`discord_notifier.py`](../src/services/discord_notifier.py)                | ログチャンネル / 結果チャンネルへの送信。embed 統一 / description / field の文字数制限に応じた切り詰めを担う                          |

`SessionManager` のタイマー遅延値は呼び出し側 cog で `DiscordConfig` から算出して
`start()` に注入します (manager 自身は config に依存しない設計)。

### Task の `play_quality` を意識する

`play_quality` は `Literal["AC", "FC", "プレイ"]` で、お題ごとに「どのプレイをカウントする
か」を表現します。新しい type を追加する際は、評価関数本体は素直にマッチ判定だけ書けば
よく、品質フィルタは `TaskEvaluator._satisfies_quality` が自動で適用してくれます。
累積系 (`level_total` / `result_*_total`) は内部で `all_plays` を再フィルタしてから集計します。

### 画像回転角度の決定タイミング

回転は「セッション開始時に 1 度だけ角度を決め、以降の再合成では同じ角度を再利用する」
方式です。
[StartSessionCog](../src/cogs/start_session.py) で `ImageProcessor.pick_rotation_angle()` を
呼んで `Session.rotation_angle` に保存し、`/play` のパネルめくり再合成や
`SessionFinalizer` の結果画像合成では同じ値を渡します。新規 cog で画像を再合成する場合も
`session.rotation_angle` をそのまま `compose` に渡してください。


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
    interaction.response.send_message.assert_called_once()
    # embed 統一方針のため、kwargs["embed"] の中身をアサートする
    sent_embed = interaction.response.send_message.call_args.kwargs["embed"]
    assert sent_embed.description == "ok"
```

`SessionManager` はシングルトンなので、テスト間で状態が漏れないように `end()` / `reset()` を
fixture の teardown で呼ぶか、`SessionManager._current = None` で明示的にリセットしてください。


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

ログレベルは環境ごとに最適化されています。

| 環境       | コンソール | ファイル | 目的                                                   |
| :--------- | :--------- | :------- | :----------------------------------------------------- |
| **開発**   | DEBUG      | DEBUG    | 開発中のデバッグ。全ログを確認可能                     |
| **テスト** | INFO       | DEBUG    | テスト結果は本番に近い条件。失敗時はファイルで詳細確認 |
| **本番**   | WARNING    | INFO     | コンソール出力最小化。ファイルに運用情報を記録         |


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

スラッシュコマンド実行中に発生した未捕捉の例外は
[SDBsBot.on_app_command_error](../src/core/bot.py) が捕捉し、`DiscordNotifier.notify_error`
でログチャンネルへ traceback 付き embed を送信、ユーザーには ephemeral の error embed を
返します (要件: 「エラーは握りつぶさず、意味のあるメッセージ付きで処理する」)。


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

Pylance による型チェックをサポートするため、関数には型ヒントを必ず付与してください。

```python
from typing import Optional
from pathlib import Path

def process_file(input_path: Path, output_dir: Path) -> Optional[dict]:
    """ファイルを処理する"""
    pass
```

`any` / `unknown` 相当の表現 (Python 側では `typing.Any` の濫用) は避け、
具体的な型を書くようにしてください。

### ドキュメンテーション

モジュール、クラス、関数には docstring を付与してください。WHY (なぜそうしたか) を
中心に書き、WHAT (何をしているか) はコード自体で読み取れる場合は省略します。

```python
def validate_email(email: str) -> bool:
    """
    メールアドレスの妥当性をチェック

    Args:
        email: チェック対象のメールアドレス

    Returns:
        有効な形式の場合 True

    Raises:
        TypeError: email が文字列でない場合
    """
    pass
```
