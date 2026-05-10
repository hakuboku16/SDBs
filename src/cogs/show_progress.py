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

from src.cogs._helpers import build_error_embed, build_topic_field
from src.services.session import Session
from src.services.session_manager import SessionManager

# モジュールスコープのロガー (production では `__main__` 親ロガーから propagate)
logger = logging.getLogger(__name__)

# ==================================================
# embed フォーマット定数
# ==================================================
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
                embed=build_error_embed(
                    "進行中のセッションがありません。/start で新しいセッションを開始してください。"
                ),
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

        達成数はタイトルに集約 (``📊 現在の進捗 (X/Y クリア)``) し、
        各タスクは 1 件 1 field で並べます (パネル番号 / 進捗 / お題内容)。
        field の整形は `build_topic_field` に集約 (`/start` `/play` と同形式)。

        Discord の 25 fields 上限はパネル数最大 25 とちょうど一致するため、
        25 パネル時は本タイトルが追加 field を持たない設計でぴったり収まります。

        Args:
            session: 進捗を表示するセッション

        Returns:
            タスク一覧と達成数をまとめた `discord.Embed`
        """
        cleared_count: int = sum(1 for task in session.tasks if task.cleared)
        total_count: int = len(session.tasks)

        embed = discord.Embed(
            title=f"📊 現在の進捗 ({cleared_count}/{total_count} クリア)",
            color=_EMBED_COLOR,
        )
        for index, task in enumerate(session.tasks):
            name, value = build_topic_field(index, task)
            embed.add_field(name=name, value=value, inline=False)
        return embed


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
