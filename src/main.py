import logging

from src.bot.client import GameBot
from src.core.config import settings
from src.core.logger import setup_logger


def main() -> None:
    """bot を構成して起動する。

    ロガーを初期化し、設定の token で GameBot を起動する。
    token 未設定なら警告を出して起動を中止する。
    """
    setup_logger()
    logger = logging.getLogger(__name__)
    if not settings.discord_token:
        logger.warning("discord_token is not set; aborting startup")
        return
    bot = GameBot(settings)
    # discord.py の既定ログ設定(basicConfig 相当)で自前ハンドラを上書きさせない。
    bot.run(settings.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
