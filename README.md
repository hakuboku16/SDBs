# Python Project Template

Python プロジェクトのテンプレート。ログ出力・環境別設定の共通基盤を含む。

## 構成

```
template/
├── .env.example
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml          # uv 管理
├── src/
│   ├── main.py             # エントリーポイント
│   └── core/
│       ├── config.py       # 環境別 Settings
│       └── logger.py       # ロガーセットアップ
└── tests/
```

## セットアップ

```bash
cp .env.example .env
uv sync
```

## 実行

ローカル:

```bash
uv run python -m src.main
```

Docker:

```bash
docker compose up --build
```

## 環境切替

`APP_ENV` で `development` / `test` / `production` を切り替える。
未指定時は `development`。

| 設定方法          | 例                                                |
| ----------------- | ------------------------------------------------- |
| `.env` ファイル   | `APP_ENV=production`                              |
| OS 環境変数 (CLI) | `APP_ENV=test uv run python -m src.main`          |
| Docker            | `docker-compose.yml` の `environment:`            |
| pytest            | `tests/conftest.py` で `APP_ENV=test` を強制      |

## テスト

```bash
uv run pytest
```

## 新規プロジェクトでの利用

このディレクトリをコピー → `.env.example` を `.env` にリネーム → `uv sync` で着手可能。
