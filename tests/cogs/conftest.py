"""
cog テスト用の共通 fixture / ヘルパー

discord.py の `Interaction` は読み取り専用属性が多く、テストで直接構築するのが困難です。
本 conftest ではテストに必要な最小限の振る舞いだけを `MagicMock` / `AsyncMock` で
差し替えた擬似 Interaction を提供します。具体的に差し替える属性は以下です:

* `user` (id / display_name)
* `channel` / `channel_id` / `guild_id`
* `response.send_message` (AsyncMock)
* `response.is_done()` (MagicMock。デフォルトは False)
* `followup.send` (AsyncMock)
* `command.qualified_name` (任意指定可)

cog のテストはこれを介して「`send_message` が ephemeral で呼ばれたか」「followup
が呼ばれたか」「指定 user_id がパラメータに渡ったか」等を検証します。
"""

from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest


# ==================================================
# 擬似 Interaction ファクトリ
# ==================================================
def make_mock_interaction(
    *,
    user_id: int = 1001,
    user_name: str = "tester",
    channel_id: int = 2001,
    guild_id: int = 3001,
    command_name: Optional[str] = None,
    is_response_done: bool = False,
) -> MagicMock:
    """
    cog テスト用の擬似 `discord.Interaction` を組み立てる

    Args:
        user_id: 呼び出し元ユーザーの ID
        user_name: 呼び出し元ユーザーの表示名
        channel_id: 呼び出し元チャンネル ID
        guild_id: 呼び出し元 Guild ID
        command_name: `interaction.command.qualified_name` に設定する値
            (None なら `command` 属性そのものを None にする)
        is_response_done: `response.is_done()` の戻り値

    Returns:
        テストで操作可能な属性を備えたモックインスタンス。
        `response.send_message` / `followup.send` は `AsyncMock` で、
        await した呼び出し回数を `assert_*` 系で検証できます。
    """
    interaction: MagicMock = MagicMock(spec=discord.Interaction)

    # ユーザー
    user: MagicMock = MagicMock(spec=discord.User)
    user.id = user_id
    user.display_name = user_name
    user.name = user_name
    interaction.user = user

    # チャンネル / Guild
    # cog 側で `isinstance(channel, discord.abc.Messageable)` でナローしている箇所が
    # あるため、spec に `discord.TextChannel` (Messageable のサブクラス) を指定して
    # isinstance チェックを通るようにする。
    interaction.channel_id = channel_id
    interaction.guild_id = guild_id
    interaction.channel = MagicMock(spec=discord.TextChannel)
    interaction.channel.id = channel_id

    # response (送信前応答)
    response = MagicMock()
    response.send_message = AsyncMock()
    response.defer = AsyncMock()
    response.is_done = MagicMock(return_value=is_response_done)
    interaction.response = response

    # followup (応答後送信)
    followup = MagicMock()
    followup.send = AsyncMock()
    interaction.followup = followup

    # command (`on_app_command_error` のような所で参照される)
    if command_name is None:
        interaction.command = None
    else:
        command = MagicMock()
        command.qualified_name = command_name
        interaction.command = command

    return interaction


# ==================================================
# fixture
# ==================================================
@pytest.fixture
def mock_interaction() -> MagicMock:
    """
    既定パラメータで生成した擬似 Interaction を返す fixture

    値を上書きしたい場合は直接 `make_mock_interaction(...)` を呼んでください。
    """
    return make_mock_interaction()
