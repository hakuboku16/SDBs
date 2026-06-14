# DEEMO × アタック25 Discord Bot

リズムゲーム DEEMO の知識を使い、クイズ番組「アタック25」風の盤面で遊ぶ Discord bot。

## 概要

- DEEMO に関する「お題」を複数生成し、お題の数だけ盤面パネルを作る
- パネルの背後に 1 枚の楽曲画像(隠し曲)を隠す
- プレイヤーが楽曲のプレイ結果を申告するとお題が進行し、達成されたお題のパネルがめくれて画像が部分開示される
- 部分開示された画像から隠し曲名を当てる

盤面は `4 / 9 / 16 / 25`(=2×2/3×3/4×4/5×5)から選択。画像は回転・グレースケール・モザイクで難易度を調整できる。セッションはインメモリ管理で、既定 30 分(残り 10 分で予告)で自動終了する。

## 必要環境

- Python 3.12 以上
- [uv](https://docs.astral.sh/uv/)(依存管理)
- Discord Bot トークンと、ゲーム用・ログ用・アーカイブ用チャンネル
- 主要依存: `discord.py`、`Pillow`、`pydantic-settings`

## セットアップ

```bash
cp .env.example .env   # 各種トークン・ID を記入
uv sync
```

### 環境変数(.env)

| 変数 | 必須 | 説明 |
| --- | --- | --- |
| `APP_ENV` | ○ | `development` / `test` / `production`(未指定時は `development`) |
| `DISCORD_TOKEN` | ○ | Discord Bot トークン(秘匿) |
| `GAME_GUILD_ID` | ○ | ゲームを動かすギルド ID |
| `LOG_GUILD_ID` | ○ | ログ送信先ギルド ID |
| `LOG_CHANNEL_ID` | ○ | WARNING 以上のログを流すチャンネル ID |
| `ARCHIVE_CHANNEL_ID` | ○ | セッション終了時のアーカイブ投稿先チャンネル ID |

データ/アセットのパス(`SONGS_DATA_PATH`・`TOPICS_DATA_PATH`・`IMAGES_DIR`)とセッション時間(`SESSION_DURATION_MINUTES=30`・`SESSION_WARNING_MINUTES=10`)も環境変数で上書きできる(既定値は [src/core/config.py](src/core/config.py) を参照)。

## 実行

ローカル:

```bash
uv run python -m src.main
```

Docker:

```bash
docker compose up --build
```

## スラッシュコマンド

| コマンド | 引数 | 説明 |
| --- | --- | --- |
| `/session_start` | `panels`, `rotate`, `grayscale`, `mosaic` | セッションを開始。隠し曲を抽選し、お題と盤面を投稿してタイマーを開始 |
| `/report` | `song`, `difficulty`, `combo`, `charming` | プレイ結果を申告。全お題と照合し、達成パネルを開示。該当お題は公開表示 |
| `/answer` | `song` | 隠し曲を回答(ephemeral)。正解者を記録し、ゲームは継続 |
| `/progress` | - | 現在の盤面・お題進捗・残り時間を表示(ephemeral) |
| `/session_end` | - | その時点の盤面をアーカイブへ投稿してセッション終了 |
| `/session_clear` | - | アーカイブを残さずアクティブセッションを強制破棄(復旧用) |

`/session_start` の画像加工オプション(既定はいずれも「しない」):

- **panels**: `4 / 9 / 16 / 25`(既定 9)
- **rotate**: 0/90/180/270° からランダム選択し、セッション中固定
- **grayscale**: グレースケール化
- **mosaic**: 弱(150px)/中(90px)/強(45px)/最強(27px)

## アーキテクチャ

ゲームロジックを `game/`(Discord 非依存・単体テスト可能)に集約し、`cogs/` は入出力の薄いアダプタに留める。

```
src/
  main.py                 # bot 起動(設定読込 → ロガー → Bot.run)
  core/
    config.py             # 環境別 Settings(Discord/ゲーム設定を含む)
    logger.py             # ロガーセットアップ
  bot/
    client.py             # discord.py Bot サブクラス(cog ロード・command sync)
    discord_log_handler.py# WARNING+ を非同期キュー経由でログ ch へ送る Handler
    game_service.py       # Discord 層が持つセッション付随状態(メッセージ参照・タイマー)
  game/
    models.py             # Song / Topic / PlayReport / GameSession の dataclass
    song_repository.py    # 楽曲データ読込・部分一致検索・画像解決・一覧導出
    topic_catalog.py      # お題テンプレート読込
    topic_types.py        # 型ごとの生成器・述語・進捗種別・説明整形のレジストリ
    topic_generator.py    # 実在曲で必ず達成可能なお題を N 個生成
    play_matcher.py       # 申告を全お題に照合し進捗加算・新規達成を検出
    session_manager.py    # 単一アクティブセッションのライフサイクル・タイマー
    board.py              # Pillow による盤面合成(画像加工・分割・被覆・開示)
  cogs/                   # 1 スラッシュコマンド 1 ファイル
assets/
  data/                   # all_songs.json / all_topics.json
  images/                 # 楽曲画像
docs/superpowers/         # 設計(specs)・実装計画(plans)
```

設計の詳細は [docs/superpowers/specs/2026-06-04-deemo-attack25-bot-design.md](docs/superpowers/specs/2026-06-04-deemo-attack25-bot-design.md) を参照。

## テスト

```bash
uv run pytest
```

`tests/conftest.py` が `APP_ENV=test` を強制する。ゲームロジック(`game/`)を中心に TDD で構築されている。

## 環境切替

`APP_ENV` で `development` / `test` / `production` を切り替える(未指定時は `development`)。

| 設定方法 | 例 |
| --- | --- |
| `.env` ファイル | `APP_ENV=production` |
| OS 環境変数 (CLI) | `APP_ENV=test uv run python -m src.main` |
| Docker | `docker-compose.yml` の `environment:` |
| pytest | `tests/conftest.py` で `APP_ENV=test` を強制 |
