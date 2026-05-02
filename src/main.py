"""
メインエントリーポイント

このファイルがアプリケーションの起点となります。
設定の読み込みとログの初期化を行った後、メインの処理を実行します。
"""

import argparse
from os import getenv

from dotenv import load_dotenv

from core.config import get_config, set_environment
from core.logger import setup_logger
from utils.helpers import get_absolute_path


def ensure_env_loaded() -> None:
    """
    ローカル開発用に .env が存在すれば読み込む
    """
    env_path = get_absolute_path(".env")
    if not env_path.exists():
        return

    load_dotenv(env_path, override=True)


def get_environment() -> str:
    """
    CLI 引数 / .env / デフォルト の順で環境を決定する

    Returns:
        str: 実行環境 (development, production, test)
    """
    allowed = ("development", "production", "test")

    # 1) CLI 引数が優先
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--env", choices=allowed)
    args, _ = parser.parse_known_args()
    if args.env:
        return args.env

    # 2) .env から取得
    ensure_env_loaded()
    env_value = getenv("ENVIRONMENT")
    if env_value:
        env_normalized = env_value.strip().lower()
        if env_normalized in allowed:
            return env_normalized
        raise ValueError(
            f"環境変数 ENVIRONMENT の値が不正です: '{env_value}'. 有効な値: {', '.join(allowed)}"
        )

    # 3) デフォルトを返す
    return "development"


def main() -> None:
    """
    メイン処理
    """
    environment = get_environment()

    # アプリケーション全体で使用する環境を設定
    # この呼び出し以降、config.py の全ヘルパー関数がこの環境を使用します
    set_environment(environment)

    # 設定の読み込み
    config = get_config()

    # ロガーの設定
    # 他モジュールで同じロガーを使う場合: logging.getLogger("__main__")
    logger = setup_logger(__name__)

    # アプリケーション起動ログ
    logger.info("=" * 40)
    logger.info(f"実行環境: {environment}")
    logger.debug(f"プロジェクト名: {config.raw_config['project_name']}")
    logger.debug(f"バージョン: {config.raw_config['version']}")

    logger.info("処理を開始します")

    try:
        # 実際の処理をここに記述
        pass

    except Exception as e:
        logger.error(f"エラーが発生しました: {e}", exc_info=True)
        raise
    finally:
        logger.info("処理を終了します")


if __name__ == "__main__":
    main()  # pragma: no cover
