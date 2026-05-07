<!-- omit in toc -->
# SDBs — Deemo × アタック25 Discord Bot

リズムゲーム「Deemo」とクイズ番組「アタック25」を掛け合わせた Discord Bot です。
ランダムに選ばれた楽曲のジャケット画像を N 枚（4/9/16/25）のパネルで覆い、
プレイヤーが Deemo をプレイしてお題をクリアするとパネルがめくられ、
徐々に見えてくる楽曲を当てるゲームを進行します。

設計詳細は [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)、
開発手順は [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) を参照してください。

<!-- omit in toc -->
## 目次
- [スラッシュコマンド](#スラッシュコマンド)
- [開発環境](#開発環境)
- [セットアップ](#セットアップ)
- [実行方法](#実行方法)
  - [ローカル実行](#ローカル実行)
  - [Docker 実行（推奨・24h 稼働）](#docker-実行推奨24h-稼働)
- [環境変数設定](#環境変数設定)
- [設定ファイル](#設定ファイル)
- [テストの実行](#テストの実行)
- [開発時の環境切り替え](#開発時の環境切り替え)
- [プロジェクト構成](#プロジェクト構成)
- [ライセンス](#ライセンス)


## スラッシュコマンド

| コマンド    | 概要                                                                                            |
| :---------- | :---------------------------------------------------------------------------------------------- |
| `/start`    | セッションを開始。`panels` `rotate` `grayscale` `mosaic` を選択し、楽曲とお題を生成・ピン留め。 |
| `/end`      | セッションを終了。結果チャンネルへ embed（マスク済み楽曲名・パネル画像・正解者一覧）を投稿。    |
| `/reset`    | セッションを破棄してピン留めを解除（結果チャンネルへの投稿なし）。                              |
| `/play`     | プレイ結果（楽曲・難易度・charming・combo）を入力し、お題進捗を自動判定。                       |
| `/answer`   | 楽曲を回答。本人にのみ ephemeral で `○ 正解です` / `× 不正解です` を返す。                      |
| `/progress` | 現セッションのお題一覧と進捗を表示。                                                            |

詳細仕様（`/answer` がセッションを終了させない理由、お題自動判定の戦略パターンなど）は
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) を参照してください。

セッションの制限時間は 30 分（10 分前に通知）。同時に存在できるセッションは 1 つだけです。


## 開発環境

- Windows 11 Home: 25H2
- [Python](https://www.python.org/downloads/): 3.13.4（Docker 利用時は不要）
- [Docker Desktop](https://www.docker.com/products/docker-desktop/)（本番運用時に推奨）
- [VSCode](https://code.visualstudio.com/): 1.101.0


## セットアップ

**1. リポジトリの取得**
```bash
git clone <gitのURL>
cd SDBs
```

**2. Discord Bot トークンの取得**

[Discord Developer Portal](https://discord.com/developers/applications) でアプリケーションを作成し、
Bot トークンを発行してください。Bot は最低限 `applications.commands` スコープでサーバーに招待します。

**3. 環境変数の設定**
```bash
copy .env.example .env
```
`.env` を開き、`DISCORD_TOKEN` に発行済みトークンを設定します。

**4. ローカル実行する場合のみ：仮想環境と依存パッケージ**
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

### Docker 実行（推奨・24h 稼働）

```bash
# 起動（バックグラウンド）
docker compose up --build -d

# ログ追従
docker compose logs -f

# 停止
docker compose down
```

`./logs` と `./assets` はホスト側にマウントされるため、再ビルドなしでログ閲覧・画像差し替えが可能です。
`restart: always` により、コンテナが落ちた場合も自動復旧します。


## 環境変数設定

`.env.example` をコピーして `.env` を作成し、以下を設定してください。

| 変数                 | 必須 | 説明                                                                    |
| :------------------- | :--: | :---------------------------------------------------------------------- |
| `DISCORD_TOKEN`      |  ◯   | Discord Bot トークン                                                    |
| `ENVIRONMENT`        |      | 実行環境 (`development` / `production` / `test`)。既定 `development`    |
| `LOG_CHANNEL_ID`     |      | エラーログ送信先の Discord チャンネル ID。未設定なら送信スキップ        |
| `RESULT_CHANNEL_ID`  |      | セッション終了時の結果送信先チャンネル ID。未設定なら送信スキップ       |


## 設定ファイル

[config/](config/) 配下の YAML で挙動を制御します。`settings.yaml` が共通設定で、
環境別ファイルが値を上書きします。

| ファイル                                                          | 用途                                  |
| :---------------------------------------------------------------- | :------------------------------------ |
| [config/settings.yaml](config/settings.yaml)                       | 共通設定                              |
| [config/settings.development.yaml](config/settings.development.yaml) | 開発環境（ログレベル等）              |
| [config/settings.production.yaml](config/settings.production.yaml) | 本番環境（ログレベル等）              |
| [config/settings.test.yaml](config/settings.test.yaml)             | テスト用                              |

主な Bot 関連項目（[config/settings.yaml](config/settings.yaml)）:

| キー                                | 説明                                                      |
| :---------------------------------- | :-------------------------------------------------------- |
| `discord.command_sync_guilds`       | 開発時の即時反映用 Guild ID 配列。本番は空でグローバル登録 |
| `discord.session_timeout_minutes`   | セッション制限時間（分）。既定 `30`                        |
| `discord.warning_minutes_before_end`| 終了前の警告通知タイミング（分）。既定 `10`                |
| `session.default_panel_count`       | パネル枚数の既定値。`9`                                    |
| `session.allowed_panel_counts`      | 選択可能なパネル枚数。`[4, 9, 16, 25]`                     |
| `session.mosaic_levels`             | モザイク強度ラベル → ブロック画素数の対応                   |

> **チャンネル ID** (ログ送信先 / 結果送信先) は yaml ではなく `.env` で管理します
> (`LOG_CHANNEL_ID` / `RESULT_CHANNEL_ID`)。詳細は[環境変数設定](#環境変数設定)を参照してください。


## テストの実行

```bash
# 全テスト
pytest

# 特定モジュール
pytest tests/cogs/test_start_session.py

# カバレッジ付き
pytest --cov=src
```

[pytest.ini](pytest.ini) で `--cov=src` がデフォルト設定されています。


## 開発時の環境切り替え

```powershell
$env:ENVIRONMENT='test'; python src/main.py
$env:ENVIRONMENT='production'; python src/main.py
```

開発時にスラッシュコマンドを即時反映したい場合は、
[config/settings.development.yaml](config/settings.development.yaml) の
`discord.command_sync_guilds` に開発用 Guild ID を追加してください
（グローバル同期は反映に最大 1 時間かかります）。


## プロジェクト構成

```
.
├── assets/                       # 楽曲データ・お題定義・ジャケット画像
│   ├── data/
│   │   ├── all_songs.json        # 楽曲メタデータ
│   │   └── all_topics.json       # お題定義
│   └── images/                   # 楽曲ジャケット画像（300×300 RGB）
├── config/                       # 設定ファイル（共通 + 環境別オーバーライド）
├── docs/
│   ├── ARCHITECTURE.md           # 設計の単一参照源
│   └── DEVELOPMENT.md            # 開発ガイド
├── logs/                         # ログ出力先（Docker でホストマウント）
├── src/
│   ├── main.py                   # エントリーポイント（Bot 起動）
│   ├── core/
│   │   ├── bot.py                # SDBsBot（cog 自動ロード・コマンド同期・エラーハンドラ）
│   │   ├── config.py             # YAML 設定 + Pydantic モデル
│   │   └── logger.py             # ログ管理
│   ├── cogs/                     # スラッシュコマンド（1 コマンド = 1 ファイル）
│   │   ├── _helpers.py           # 楽曲名オートコンプリート等の共通関数
│   │   ├── start_session.py      # /start
│   │   ├── end_session.py        # /end
│   │   ├── reset_session.py      # /reset
│   │   ├── input_play.py         # /play
│   │   ├── answer_song.py        # /answer
│   │   └── show_progress.py      # /progress
│   ├── services/                 # ドメインロジック（Discord 非依存が原則）
│   │   ├── session.py            # Session / PlayRecord
│   │   ├── session_manager.py    # シングルトン + タイマー
│   │   ├── session_finalizer.py  # /end と自動タイムアウトの共通終了処理
│   │   ├── task.py               # Task モデル
│   │   ├── task_generator.py     # all_topics.json から N 個ランダム生成
│   │   ├── task_evaluator.py     # type ごとの評価関数（戦略パターン）
│   │   ├── song_repository.py    # all_songs.json ロード + 部分一致検索
│   │   ├── image_processor.py    # Pillow でパネル合成・回転・グレースケール・モザイク
│   │   └── discord_notifier.py   # ログ/結果チャンネルへの送信
│   └── utils/
│       ├── helpers.py            # ファイル I/O 等
│       └── validators.py         # バリデーション関数
├── tests/                        # pytest テスト（src と対称な構成）
├── .env.example                  # 環境変数テンプレート
├── Dockerfile                    # python:3.13-slim ベース、非 root 実行
├── docker-compose.yml            # 24h 稼働、./logs ./assets をマウント
├── pytest.ini                    # pytest 設定（--cov=src）
├── requirements.txt              # 依存ライブラリ
└── README.md                     # 本ファイル
```


## ライセンス
このプロジェクトは MIT ライセンスに基づいてライセンスされています。詳細については LICENSE ファイルを参照してください。
