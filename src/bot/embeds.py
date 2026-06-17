from __future__ import annotations

from enum import IntEnum

import discord


class EmbedColor(IntEnum):
    """メッセージの意味ごとに割り当てる Embed の色。"""

    SUCCESS = 0x57F287  # 緑: 成功・確認
    ERROR = 0xED4245  # 赤: エラー・不正解
    WARNING = 0xE67E22  # オレンジ: 予告・ガード
    INFO = 0x3498DB  # 青: 情報(盤面・進捗)
    NEUTRAL = 0x95A5A6  # 灰: アーカイブ


def _build(
    color: EmbedColor, description: str | None, title: str | None
) -> discord.Embed:
    """指定色の Embed を組み立てる。

    Args:
        color: 左縁のカラーバーに使う色。
        description: 本文。None なら本文なし。
        title: 見出し。None なら見出しなし。

    Returns:
        discord.Embed: 構築した Embed。
    """
    return discord.Embed(title=title, description=description, color=discord.Color(color))


def success(description: str | None = None, *, title: str | None = None) -> discord.Embed:
    """成功・確認を表す緑色の Embed を返す。

    Args:
        description: 本文。
        title: 見出し。

    Returns:
        discord.Embed: 緑色の Embed。
    """
    return _build(EmbedColor.SUCCESS, description, title)


def error(description: str | None = None, *, title: str | None = None) -> discord.Embed:
    """エラー・不正解を表す赤色の Embed を返す。

    Args:
        description: 本文。
        title: 見出し。

    Returns:
        discord.Embed: 赤色の Embed。
    """
    return _build(EmbedColor.ERROR, description, title)


def warning(description: str | None = None, *, title: str | None = None) -> discord.Embed:
    """予告・ガードを表すオレンジ色の Embed を返す。

    Args:
        description: 本文。
        title: 見出し。

    Returns:
        discord.Embed: オレンジ色の Embed。
    """
    return _build(EmbedColor.WARNING, description, title)


def info(description: str | None = None, *, title: str | None = None) -> discord.Embed:
    """情報を表す青色の Embed を返す。

    Args:
        description: 本文。
        title: 見出し。

    Returns:
        discord.Embed: 青色の Embed。
    """
    return _build(EmbedColor.INFO, description, title)


def neutral(description: str | None = None, *, title: str | None = None) -> discord.Embed:
    """アーカイブを表す灰色の Embed を返す。

    Args:
        description: 本文。
        title: 見出し。

    Returns:
        discord.Embed: 灰色の Embed。
    """
    return _build(EmbedColor.NEUTRAL, description, title)
