"""
Discord Bot 本体を提供するモジュール

`SDBsBot` は `discord.ext.commands.Bot` を継承し、以下を担います:

* `src/cogs/` 配下の全 cog を自動ロード (要件: 「1スラッシュコマンドにつき1モジュール」)
* スラッシュコマンドツリーの同期 (Guild ID 指定があれば即時同期、空ならグローバル登録)
* スラッシュコマンドで未捕捉の例外をログチャンネルへ通知し、ユーザーには ephemeral で
  エラーメッセージを返却 (要件: 「エラーは握りつぶさず、意味のあるメッセージ付きで処理する」)

`DiscordNotifier` は Bot 属性 (`self.notifier`) として保持し、各 cog から
`self.bot.notifier` で参照できるようにします。
"""

import importlib
import logging
import pkgutil
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from src.cogs._helpers import build_error_embed
from src.core.config import DiscordConfig
from src.services.discord_notifier import DiscordNotifier

# モジュールスコープのロガー (production では `__main__` 親ロガーから propagate)
logger = logging.getLogger(__name__)


# ==================================================
# SDBsBot
# ==================================================
class SDBsBot(commands.Bot):
    """
    Deemo × アタック25 Discord Bot のメインクラス

    `commands.Bot` を継承し、`setup_hook` で cog 自動ロードとコマンドツリー同期を行います。
    スラッシュコマンドのみを使用するため `command_prefix` は名目上のダミー値です。

    Attributes:
        config: Discord 設定 (channel ID やコマンド同期対象 Guild など)
        notifier: ログ/結果チャンネルへの通知ラッパ。`setup_hook` で生成されるまで None
    """

    # cog を自動ロードする対象パッケージ (`src.cogs`)
    _COGS_PACKAGE: str = "src.cogs"

    # スラッシュコマンドのみで運用するためのダミー prefix
    # commands.Bot は command_prefix が必須だが、本 Bot ではテキストコマンドを受け付けない
    _DUMMY_PREFIX: str = "!sdbs-unused "

    def __init__(
        self,
        config: DiscordConfig,
        *,
        intents: Optional[discord.Intents] = None,
    ) -> None:
        """
        Bot を初期化する

        Args:
            config: Discord 設定オブジェクト
            intents: Gateway Intents。省略時は `discord.Intents.default()` を使用
        """
        super().__init__(
            command_prefix=self._DUMMY_PREFIX,
            intents=intents if intents is not None else discord.Intents.default(),
            help_command=None,
        )
        self.config: DiscordConfig = config
        # setup_hook で初期化される。cog 側からは self.bot.notifier で参照する想定
        self.notifier: Optional[DiscordNotifier] = None

    # --------------------------------------------------
    # ライフサイクル
    # --------------------------------------------------
    async def setup_hook(self) -> None:
        """
        Bot 起動直前に discord.py から呼ばれるフック

        以下を順に実施します:
            1. `DiscordNotifier` を生成し `self.notifier` に保持
            2. `src/cogs/` 配下の全モジュールを `load_extension` で自動ロード
            3. スラッシュコマンドツリーを同期 (Guild ID 指定があれば各 Guild へ、空ならグローバル)
        """
        # 1) Notifier を先に用意 (cog やエラーハンドラから参照されるため)
        self.notifier = DiscordNotifier(self, self.config)

        # 2) cog 自動ロード
        await self._load_all_cogs()

        # 3) コマンドツリーの同期
        await self._sync_command_tree()

    async def _load_all_cogs(self) -> None:
        """
        `src/cogs/` 配下の全モジュールを `load_extension` でロードする

        `pkgutil.iter_modules` でパッケージを走査し、各モジュールを Bot に登録します。
        ロード失敗時は握りつぶさず WARNING を残しつつ次のモジュールを試行します
        (1 つの cog の不具合で Bot 全体が起動できないのを避けるため)。
        """
        try:
            package = importlib.import_module(self._COGS_PACKAGE)
        except ImportError as e:
            logger.warning("cog パッケージを import できませんでした: %s", e)
            return

        # `__path__` がない (実モジュールでなくパッケージでない) 場合は何もできない
        package_path = getattr(package, "__path__", None)
        if package_path is None:
            logger.warning(
                "%s はパッケージではないため cog 自動ロードをスキップします",
                self._COGS_PACKAGE,
            )
            return

        for module_info in pkgutil.iter_modules(package_path):
            # サブパッケージは想定しない (1 cog = 1 モジュール)
            if module_info.ispkg:
                continue
            # アンダースコア始まりのモジュールは cog ではないヘルパー扱いとし、
            # `load_extension` (要 `setup` 関数) の対象から除外する
            # (例: src/cogs/_helpers.py は楽曲名オートコンプリート等の共通関数を提供する)
            if module_info.name.startswith("_"):
                continue
            extension_name = f"{self._COGS_PACKAGE}.{module_info.name}"
            try:
                await self.load_extension(extension_name)
                logger.info("cog をロードしました: %s", extension_name)
            except commands.ExtensionError as e:
                # 1 つの cog の不具合で全体停止しないよう WARNING で残し継続
                logger.warning("cog のロードに失敗しました (%s): %s", extension_name, e)

    async def _sync_command_tree(self) -> None:
        """
        スラッシュコマンドツリーを同期する

        `command_sync_guilds` が指定されていれば各 Guild へ即時同期 (開発時の即時反映用)、
        空であればグローバル同期 (本番運用) します。
        """
        guild_ids: list[int] = self.config.command_sync_guilds
        if not guild_ids:
            await self.tree.sync()
            logger.info("スラッシュコマンドをグローバル同期しました")
            return

        for guild_id in guild_ids:
            guild_obj = discord.Object(id=guild_id)
            # ツリーをグローバルから対象 Guild にコピーしてから同期 (開発時の即時反映パターン)
            self.tree.copy_global_to(guild=guild_obj)
            await self.tree.sync(guild=guild_obj)
            logger.info("スラッシュコマンドを Guild=%s に同期しました", guild_id)

    # --------------------------------------------------
    # エラーハンドラ
    # --------------------------------------------------
    async def on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        """
        スラッシュコマンド実行中に発生した例外を捕捉する

        - ログチャンネルへ traceback 付きで送信 (`DiscordNotifier`)
        - ユーザーには ephemeral で短いエラーメッセージを返す
          (応答済みであれば followup、未応答であれば response.send_message)

        Args:
            interaction: コマンドのインタラクション
            error: 発生した `AppCommandError`
        """
        command_name = (
            interaction.command.qualified_name if interaction.command is not None else "<unknown>"
        )
        log_message = f"スラッシュコマンドでエラーが発生しました: /{command_name}"

        # 1) ログチャンネルへ通知 (notifier 未初期化なら logger に出すのみ)
        if self.notifier is not None:
            try:
                await self.notifier.notify_error(log_message, exc=error)
            except discord.DiscordException as notify_error:
                # 通知自体の失敗は握って logger に残す (二次障害でユーザー応答が止まらないように)
                logger.warning("ログチャンネルへの通知に失敗しました: %s", notify_error)
        else:
            logger.error("%s (notifier 未初期化)", log_message, exc_info=error)

        # 2) ユーザーへ ephemeral で返答 (Bot からの送信は embed 統一)
        user_embed = build_error_embed(
            "コマンドの実行中にエラーが発生しました。管理者にお問い合わせください。",
            title="エラー",
        )
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=user_embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=user_embed, ephemeral=True)
        except discord.DiscordException as reply_error:
            # 応答失敗 (interaction が既にタイムアウト等) はログに残し握りつぶす
            logger.warning(
                "ユーザーへのエラー応答に失敗しました (/%s): %s",
                command_name,
                reply_error,
            )
