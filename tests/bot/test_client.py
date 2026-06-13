from src.bot.client import GameBot
from src.bot.game_service import GameService
from src.core.config import get_settings


def test_gamebot_exposes_game_service() -> None:
    """GameBot は GameService を game 属性として保持する。"""
    bot = GameBot(get_settings())
    assert isinstance(bot.game, GameService)
    assert bot.game.session is None
