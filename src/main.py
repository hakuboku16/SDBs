"""
メインエントリーポイント

このファイルがアプリケーションの起点となります。
.env と設定の読み込み・ロガー初期化を経て `SDBsBot` を起動します。
"""

import argparse
import sys
from os import getenv
from pathlib import Path

from dotenv import load_dotenv

# ==================================================
# import path bootstrap
# ==================================================
# `python src/main.py` のように直接実行された場合、Python は src/ のみを
# sys.path に追加するため、`src.core.bot` 形式の絶対インポートが解決できません。
# 既存コードが `core.X` 形式 (src/ 起点) と `src.core.X` 形式の両方を使っているため、
# プロジェクトルートを sys.path 先頭に挿入することで両方を解決可能にします。
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.config import get_config, get_discord_config, set_environment  # noqa: E402
from core.logger import setup_logger  # noqa: E402
from src.core.bot import SDBsBot  # noqa: E402
from utils.helpers import get_absolute_path  # noqa: E402


# ==================================================
# 環境変数 / 環境名の解決
# ==================================================
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


def get_discord_token() -> str:
    """
    Discord Bot トークンを環境変数から取得する

    .env を読み込んだ上で `DISCORD_TOKEN` を解決します。未設定や空文字の場合は
    意味のあるメッセージで `RuntimeError` を送出します
    (要件: 「エラーは握りつぶさず、意味のあるメッセージ付きで処理する」)。

    Returns:
        str: Discord Bot トークン (前後の空白を除去済み)

    Raises:
        RuntimeError: `DISCORD_TOKEN` が未設定または空の場合
    """
    ensure_env_loaded()
    token = getenv("DISCORD_TOKEN")
    if token is None or not token.strip():
        raise RuntimeError(
            "環境変数 DISCORD_TOKEN が設定されていません。"
            ".env または実行環境に有効なトークンを設定してください"
        )
    return token.strip()


# ==================================================
# エントリーポイント
# ==================================================
def main() -> None:
    """
    Bot 起動エントリーポイント

    実行環境を決定 → 設定とロガーを初期化 → トークンを解決 → `SDBsBot` を起動します。
    トークン未設定時はロガーへエラー出力した上で `SystemExit(1)` で終了します。
    """
    environment = get_environment()

    # アプリケーション全体で使用する環境を設定
    set_environment(environment)

    # 設定とロガーの初期化
    config = get_config()
    logger = setup_logger(__name__)

    logger.info("=" * 40)
    logger.info(f"実行環境: {environment}")
    logger.debug(f"プロジェクト名: {config.raw_config['project_name']}")
    logger.debug(f"バージョン: {config.raw_config['version']}")

    # トークンの解決 (未設定時は意味のあるメッセージで終了)
    try:
        token = get_discord_token()
    except RuntimeError as e:
        logger.error(str(e))
        raise SystemExit(1) from e

    # Discord 設定と Bot インスタンスの構築
    discord_config = get_discord_config()
    bot = SDBsBot(discord_config)

    logger.info("Bot を起動します")
    try:
        # `Bot.run` はブロッキング呼び出しで、ログイン → イベントループ → クリーンアップを行う
        bot.run(token)
    except Exception as e:
        logger.error(f"Bot の実行中にエラーが発生しました: {e}", exc_info=True)
        raise
    finally:
        logger.info("Bot を終了します")


if __name__ == "__main__":
    main()  # pragma: no cover
