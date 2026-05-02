<!-- omit in toc -->
# テンプレートフォルダ

このリポジトリは Python プロジェクトの雛形です。  
開発を始める際にコピーしてご活用ください。  
このテンプレートは Windows 環境を想定しています。

<!-- omit in toc -->
## 目次
- [開発環境](#開発環境)
- [セットアップ](#セットアップ)
- [実行方法](#実行方法)
- [環境変数設定](#環境変数設定)
- [テストの実行](#テストの実行)
- [開発時の環境切り替え](#開発時の環境切り替え)
- [プロジェクト構成](#プロジェクト構成)
- [ライセンス](#ライセンス)


## 開発環境

- Windows 11 Home: 25H2
- [python](https://www.python.org/downloads/): 3.13.4
- [VSCode](https://code.visualstudio.com/): 1.101.0


## セットアップ

**1. プロジェクトフォルダをコピー**
```bash
# コピー先のフォルダに移動しておく
git clone <gitのURL>
```

**2. 仮想環境の作成**
```bash
# コピーしたフォルダに移動しておく
python -m venv .venv
```

**3. 仮想環境の有効化**
```bash
.venv\Scripts\activate
```

**4. 依存パッケージのインストール**
```bash
pip install -r requirements.txt
```

## 実行方法

```bash
# 仮想環境の有効化
.venv\Scripts\activate

# プログラム実行
python src/main.py
```

## 環境変数設定

`.env.example` をコピーして `.env` を作成し、プロジェクトに応じて編集してください。

```bash
copy .env.example .env
```

項目は以下の通りです。  
| 変数        | 説明                                     |
| :---------- | :--------------------------------------- |
| ENVIRONMENT | 実行環境 (development, production, test) |

## テストの実行

pytest を使用してテストを実行します。

```bash
# 全テストを実行
pytest

# 特定のテストファイルのみ実行
pytest tests/test_config.py
```

## 開発時の環境切り替え

環境を切り替える場合は、`.env` ファイルの `ENVIRONMENT` を変更するか、以下のコマンドで実行します。

```powershell
$env:ENVIRONMENT='test'; python src/main.py
$env:ENVIRONMENT='production'; python src/main.py
```

## プロジェクト構成

```
.
├── config/                       # 設定ファイル
│   ├── settings.yaml             # 全環境共通設定
│   ├── settings.development.yaml # 開発環境設定（上書き）
│   ├── settings.production.yaml  # 本番環境設定（上書き）
│   └── settings.test.yaml        # テスト環境設定（上書き）
├── docs/                         # ドキュメント
├── logs/                         # ログファイル出力先
├── src/                          # ソースコード
│   ├── __init__.py
│   ├── main.py                   # エントリーポイント
│   ├── core/                     # プログラム全体に影響するモジュール
│   │   ├── __init__.py
│   │   ├── config.py             # 設定値管理
│   │   └── logger.py             # ログ管理
│   └── utils/                    # ユーティリティモジュール
│       ├── __init__.py
│       ├── helpers.py            # ヘルパー関数
│       └── validators.py         # バリデーション関数
├── tests/                        # テストコード
│   ├── __init__.py
│   ├── conftest.py               # pytest設定・fixture
│   ├── test_main.py              # エントリーポイントのテストコード
│   ├── core/
│   │   ├── __init__.py
│   │   ├── test_config.py        # 設定管理のテストコード
│   │   └── test_logger.py        # ログ管理のテストコード
│   └── utils/
│       ├── __init__.py
│       ├── test_helpers.py       # ヘルパー関数のテストコード
│       └── test_validators.py    # バリデーション関数のテストコード
├── .env                          # 環境変数（`.env.example`をコピー）
├── .env.example                  # 環境変数テンプレート
├── .gitignore                    # git管理対象外ファイル
├── pytest.ini                    # pytest設定
├── README.md                     # このファイル
└── requirements.txt              # 依存ライブラリ一覧
```

## ライセンス
このプロジェクトは MIT ライセンスに基づいてライセンスされています。詳細については LICENSE ファイルを参照してください。
