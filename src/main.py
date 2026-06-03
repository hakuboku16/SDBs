import logging

from src.core.logger import setup_logger


def main() -> None:
    """アプリケーションのエントリーポイント。

    ロガーをセットアップし、起動メッセージを出力する。
    """
    setup_logger()
    logger = logging.getLogger(__name__)
    logger.info("application started")


if __name__ == "__main__":
    main()
