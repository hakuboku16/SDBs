"""
cog 全体で共有するヘルパーを提供するモジュール

スラッシュコマンド `/play` と `/answer` は共に「楽曲名の部分一致オートコンプリート」を
必要とするため、Discord の `app_commands.Choice` 列を返す共通実装を本モジュールに
集約します。`SongRepository` 依存はファクトリ経由で注入し、cog 側は
バインド済みコールバックを `app_commands.autocomplete` に登録する想定です。

要件「1スラッシュコマンドにつき1モジュール」に反しないよう、本モジュールは
スラッシュコマンドそのものを定義しません。アンダースコア接頭辞 (`_helpers.py`) で
パッケージ走査時に extension としてロードされない設計です
([src/core/bot.py](src/core/bot.py) の `_load_all_cogs` は `pkgutil.iter_modules` で
列挙された全モジュールを `load_extension` しますが、アンダースコア始まりは
慣例として cog 本体ではないことを示す)。

なお `pkgutil.iter_modules` はアンダースコア始まりのモジュールも列挙するため、
本モジュールには `setup` 関数を定義していません。`load_extension` は `setup`
未定義時に `commands.NoEntryPointError` を送出しますが、Bot 側のロード処理は
`commands.ExtensionError` を warning でキャッチして次のモジュールに進む実装に
なっているため、Bot 起動を妨げません (将来 setup 関数を要する形に変えたい場合は
本モジュールを別パッケージへ移動するか、Bot 側で接頭辞フィルタを追加してください)。
"""

from typing import Callable, Coroutine

import discord
from discord import app_commands

from src.services.song_repository import SongRepository


# `app_commands.autocomplete` に渡すコールバックの型エイリアス。
# 第 1 引数の Interaction は cog のメソッド形式に合わせて self を含まない関数として返す。
SongAutocomplete = Callable[
    [discord.Interaction, str],
    Coroutine[None, None, list[app_commands.Choice[str]]],
]


# ==================================================
# 楽曲名オートコンプリート
# ==================================================
def build_song_autocomplete(repository: SongRepository) -> SongAutocomplete:
    """
    `SongRepository` をクロージャに閉じ込んだ楽曲名オートコンプリート関数を返す

    Discord のオートコンプリートは「現在の入力文字列」を `current` として渡すため、
    `SongRepository.search_partial` で部分一致検索 (大文字小文字を無視) し、
    上限 25 件 (Discord の仕様上限 = `SongRepository.AUTOCOMPLETE_LIMIT`) の
    `app_commands.Choice[str]` リストを返します。

    Args:
        repository: 楽曲データのリポジトリ

    Returns:
        `app_commands.autocomplete` に登録できる async 関数
            戻り値は楽曲名 (`Song.name`) を `name` / `value` 両方に持つ Choice 列です。

    Example:
        ```python
        autocomplete = build_song_autocomplete(repo)

        @app_commands.command(name="answer")
        @app_commands.describe(song="楽曲名")
        @app_commands.autocomplete(song=autocomplete)
        async def answer(self, interaction: discord.Interaction, song: str) -> None:
            ...
        ```
    """

    async def autocomplete(
        interaction: discord.Interaction,  # noqa: ARG001  Discord 側 API として必須
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """
        現在入力されている文字列に対する候補リストを返す

        - 空文字列の場合は先頭から `AUTOCOMPLETE_LIMIT` 件を提示する
        - Discord の Choice は name / value とも 100 文字以内である必要があるが、
          楽曲名は十分短い前提のためここでは切り詰めを行わない
        """
        songs = repository.search_partial(current)
        return [
            app_commands.Choice(name=song.name, value=song.name) for song in songs
        ]

    return autocomplete
