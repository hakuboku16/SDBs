import discord

from src.bot.embeds import EmbedColor, error, info, neutral, success, warning


def test_success_sets_green_color_and_text() -> None:
    """success は緑色で title/description を設定する。"""
    embed = success("完了しました", title="確認")
    assert embed.color == discord.Color(EmbedColor.SUCCESS)
    assert embed.title == "確認"
    assert embed.description == "完了しました"


def test_error_sets_red_color() -> None:
    """error は赤色を設定する。"""
    assert error("失敗").color == discord.Color(EmbedColor.ERROR)


def test_warning_sets_orange_color() -> None:
    """warning はオレンジ色を設定する。"""
    assert warning("注意").color == discord.Color(EmbedColor.WARNING)


def test_info_sets_blue_color() -> None:
    """info は青色を設定する。"""
    assert info("情報").color == discord.Color(EmbedColor.INFO)


def test_neutral_sets_gray_color() -> None:
    """neutral は灰色を設定する。"""
    assert neutral("記録").color == discord.Color(EmbedColor.NEUTRAL)


def test_builder_allows_title_only() -> None:
    """description 省略時は title だけの Embed を作れる(画像用途)。"""
    embed = info(title="盤面とお題")
    assert embed.title == "盤面とお題"
    assert embed.description is None
