"""
cog 全体で共有するヘルパーを提供するモジュール

スラッシュコマンド `/play` と `/answer` は共に「楽曲名の部分一致オートコンプリート」を
必要とするため、Discord の `app_commands.Choice` 列を返す共通実装を本モジュールに
集約します。`SongRepository` 依存はファクトリ経由で注入し、cog 側は
バインド済みコールバックを `app_commands.autocomplete` に登録する想定です。

加えて、Bot から送信する全メッセージを embed 化する方針 (要件: 「Bot が送信する
メッセージはすべて embed 形式」) に従い、用途別の embed ビルダを提供します。
色分けは以下の通りで、用途に応じてどの cog からも同じトーンで応答できるようにします。

* 情報 (info): blurple — 通常の応答 / 進捗表示
* 成功 (success): green — 完了通知 / 正解
* 警告 (warning): orange — 残り時間警告 / 注意喚起
* エラー (error): red — バリデーション失敗 / 例外通知 / 不正解

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

from typing import Callable, Coroutine, Optional

import discord
from discord import app_commands

from src.services.song_repository import SongRepository
from src.services.task import Task


# `app_commands.autocomplete` に渡すコールバックの型エイリアス。
# 第 1 引数の Interaction は cog のメソッド形式に合わせて self を含まない関数として返す。
SongAutocomplete = Callable[
    [discord.Interaction, str],
    Coroutine[None, None, list[app_commands.Choice[str]]],
]


# ==================================================
# embed ビルダ用カラー定数
# ==================================================
# Discord embed の用途別カラー (Bot が送る全メッセージで一貫させる)
EMBED_COLOR_INFO: discord.Color = discord.Color.blurple()
EMBED_COLOR_SUCCESS: discord.Color = discord.Color.green()
EMBED_COLOR_WARNING: discord.Color = discord.Color.orange()
EMBED_COLOR_ERROR: discord.Color = discord.Color.red()

# Discord embed 仕様: description は 4096 文字まで
_DESCRIPTION_LIMIT: int = 4096
# 切り詰めマーカー (末尾を残し、先頭に挿入する)
_TRUNCATE_MARKER: str = "…(切り詰め)…\n"


def _truncate_description(description: str) -> str:
    """
    Discord embed.description の 4096 文字制限に収まるよう先頭側を切り詰める

    traceback などの長文テキストを description に格納するケースでは、底側
    (例外発生箇所) を残す方が情報量が多いため末尾を残す方針とする。
    """
    if len(description) <= _DESCRIPTION_LIMIT:
        return description
    keep: int = _DESCRIPTION_LIMIT - len(_TRUNCATE_MARKER)
    return _TRUNCATE_MARKER + description[-keep:]


# ==================================================
# embed ビルダ (用途別)
# ==================================================
def build_info_embed(
    description: str,
    *,
    title: Optional[str] = None,
    color: Optional[discord.Color] = None,
) -> discord.Embed:
    """
    情報 (info) 用の embed を組み立てる

    `/progress` のような「現在の状態を伝える」用途で使用する。色を上書きしたい場合は
    `color` を渡す (例: `/play` で進捗を緑系で示すなど)。

    Args:
        description: embed の本文
        title: embed のタイトル (省略可)
        color: 色を上書きする場合に指定 (省略時は blurple)

    Returns:
        構築済みの `discord.Embed`
    """
    return discord.Embed(
        title=title,
        description=_truncate_description(description),
        color=color if color is not None else EMBED_COLOR_INFO,
    )


def build_success_embed(
    description: str,
    *,
    title: Optional[str] = None,
) -> discord.Embed:
    """
    成功 (success) 用の embed を組み立てる (green)

    `/end` の完了応答や `/answer` の正解応答など、肯定的な結果を伝える用途で使用する。

    Args:
        description: embed の本文
        title: embed のタイトル (省略可)

    Returns:
        green カラーの `discord.Embed`
    """
    return discord.Embed(
        title=title,
        description=_truncate_description(description),
        color=EMBED_COLOR_SUCCESS,
    )


def build_warning_embed(
    description: str,
    *,
    title: Optional[str] = None,
) -> discord.Embed:
    """
    警告 (warning) 用の embed を組み立てる (orange)

    残り時間警告など「注意喚起」用途で使用する。

    Args:
        description: embed の本文
        title: embed のタイトル (省略可)

    Returns:
        orange カラーの `discord.Embed`
    """
    return discord.Embed(
        title=title,
        description=_truncate_description(description),
        color=EMBED_COLOR_WARNING,
    )


def build_error_embed(
    description: str,
    *,
    title: Optional[str] = None,
) -> discord.Embed:
    """
    エラー (error) 用の embed を組み立てる (red)

    バリデーション失敗・例外通知・`/answer` の不正解など、否定的な結果を伝える
    用途で使用する。

    Args:
        description: embed の本文
        title: embed のタイトル (省略可)

    Returns:
        red カラーの `discord.Embed`
    """
    return discord.Embed(
        title=title,
        description=_truncate_description(description),
        color=EMBED_COLOR_ERROR,
    )


# ==================================================
# お題 1 件 → embed field 用の name / value タプル
# ==================================================
# クリア済み / 未クリアを示す表示用シンボル (`/start` `/play` `/progress` で共通)
TOPIC_CLEARED_SYMBOL: str = "✅"
TOPIC_NOT_CLEARED_SYMBOL: str = "⬜"

# Discord embed field の文字数制限 (公式仕様: name 256 / value 1024)
_FIELD_NAME_LIMIT: int = 256
_FIELD_VALUE_LIMIT: int = 1024


def _truncate_for_field(text: str, limit: int) -> str:
    """
    embed field 文字数制限に収まるよう末尾を切り詰める

    field の name / value は description と異なり「先頭を残す方が情報量が多い」
    ため (お題タイトルや description テンプレート冒頭が重要)、末尾側を切り詰める。
    """
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def build_topic_field(index: int, task: Task) -> tuple[str, str]:
    """
    お題 1 件を embed の add_field 用 ``(name, value)`` に整形する

    ``name``  : ``"{symbol} パネル {index+1} ({current}/{set_value})"``
        - ``symbol`` は ``task.cleared`` で ``✅`` / ``⬜`` を切り替え
        - ``index`` は 0-origin だが表示は 1-origin に変換 (パネル画像の番号と揃える)
    ``value`` : ``task.format_description()`` (value/set/play placeholder 置換済)

    `/start` `/play` `/progress` のすべてで同じ表示を使うため、フォーマット変更時は
    本関数 1 箇所の修正で全 cog に伝播する。

    Args:
        index: 0-origin のパネル番号
        task: 表示対象の `Task`

    Returns:
        ``(field_name, field_value)`` のタプル。両者とも Discord 仕様 (name 256 /
        value 1024) に収まるよう切り詰め済み。
    """
    symbol: str = TOPIC_CLEARED_SYMBOL if task.cleared else TOPIC_NOT_CLEARED_SYMBOL
    name: str = f"{symbol} パネル {index + 1} ({task.current}/{task.set_value})"
    value: str = task.format_description()
    return (
        _truncate_for_field(name, _FIELD_NAME_LIMIT),
        _truncate_for_field(value, _FIELD_VALUE_LIMIT),
    )


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
