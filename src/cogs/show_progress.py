"""
/progress スラッシュコマンドを定義するモジュール

ARCHITECTURE.md ステップ 5.5 に従い、進行中セッションのタスク進捗を表示する処理を提供します:

1. 現セッションが無ければ ephemeral でエラー応答 (副作用無し)
2. 現セッションがある場合は各タスクの clear 状態・``current`` / ``set_value`` を
   embed として組み立て、チャンネルへ公開応答する

タスク評価ロジックは [`TaskEvaluator`](src/services/task_evaluator.py) と
`/play` 側で更新されている前提のため、本 cog は `Task` オブジェクトの参照のみを
行い、副作用は一切持ちません (情報表示専用)。
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from src.services.session import Session
from src.services.session_manager import SessionManager

# モジュールスコープのロガー (production では `__main__` 親ロガーから propagate)
logger = logging.getLogger(__name__)

# ==================================================
# 視覚化記号
# ==================================================
# クリア済み / 未クリアを示す表示用シンボル。フォント依存しない Unicode 記号を採用
_CLEARED_SYMBOL: str = "✓"
_NOT_CLEARED_SYMBOL: str = "□"

# Discord embed.description の上限 (4096 文字)。改行込みでこの長さに収める
_DESCRIPTION_LIMIT: int = 4000

# embed タイトル / 色 (`/progress` 専用)
_EMBED_COLOR: discord.Color = discord.Color.blue()


# ==================================================
# /progress cog
# ==================================================
class ShowProgressCog(commands.Cog):
    """
    `/progress` スラッシュコマンドを提供する cog

    `SessionManager` シングルトンから現セッションを参照し、embed を組み立てて返すだけの
    純粋な情報表示コマンドです。外部依存は SessionManager のみのため、コンストラクタ
    引数は ``bot`` のみで構成しています。
    """

    def __init__(self, bot: commands.Bot) -> None:
        """
        cog を初期化する

        Args:
            bot: 親 Bot インスタンス (`SDBsBot` を想定)
        """
        super().__init__()
        self.bot: commands.Bot = bot

    # --------------------------------------------------
    # スラッシュコマンド本体
    # --------------------------------------------------
    @app_commands.command(
        name="progress",
        description="進行中セッションのタスク進捗を表示します",
    )
    async def progress(self, interaction: discord.Interaction) -> None:
        """
        進行中セッションのタスク進捗を embed として表示する

        - セッションが無い場合は ephemeral でエラー応答
        - セッションがある場合は公開応答 (defer 不要 / I/O なしのため即時送信)
        """
        manager: SessionManager = SessionManager.instance()
        session = manager.current()

        if session is None:
            await interaction.response.send_message(
                "進行中のセッションがありません。/start で新しいセッションを開始してください。",
                ephemeral=True,
            )
            return

        embed = self._build_progress_embed(session)
        await interaction.response.send_message(embed=embed)

    # --------------------------------------------------
    # embed 構築
    # --------------------------------------------------
    @staticmethod
    def _build_progress_embed(session: Session) -> discord.Embed:
        """
        セッションのタスク進捗を embed として組み立てる

        各タスクは ``[symbol] index. type(value): current/set_value`` 形式で
        1 行ずつ description に列挙します。``value`` が None のタスクは値部分を省略します。

        Args:
            session: 進捗を表示するセッション

        Returns:
            タスク一覧と達成数をまとめた `discord.Embed`
        """
        cleared_count: int = sum(1 for task in session.tasks if task.cleared)
        total_count: int = len(session.tasks)

        # 1 タスク 1 行で description に並べる
        lines: list[str] = []
        for index, task in enumerate(session.tasks, start=1):
            symbol = _CLEARED_SYMBOL if task.cleared else _NOT_CLEARED_SYMBOL
            value_part = f" ({task.value})" if task.value is not None else ""
            lines.append(
                f"{symbol} {index}. {task.type}{value_part}: "
                f"{task.current}/{task.set_value}"
            )

        body: str = "\n".join(lines)
        # description 上限を超える場合は末尾を省略 (パネル数 25 + 長い value で稀に到達)
        if len(body) > _DESCRIPTION_LIMIT:
            body = body[: _DESCRIPTION_LIMIT - 1] + "…"

        return discord.Embed(
            title=f"現在の進捗 ({cleared_count}/{total_count} クリア)",
            description=body,
            color=_EMBED_COLOR,
        )


# ==================================================
# extension エントリポイント
# ==================================================
async def setup(bot: commands.Bot) -> None:
    """
    `Bot.load_extension` から呼ばれる cog 登録関数

    `/progress` は外部依存を持たないため、cog 単独で構築・登録します。
    """
    cog = ShowProgressCog(bot)
    await bot.add_cog(cog)
