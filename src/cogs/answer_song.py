"""
/answer スラッシュコマンドを定義するモジュール

ARCHITECTURE.md ステップ 5.7 に従い、メンバーがパネルに隠された楽曲名を回答する処理を提供します:

1. 引数 (`song`) を受け取り、`SongRepository` に存在するかを確認
2. 進行中セッションが無ければ ephemeral でエラー応答 (副作用なし)
3. 回答内容と `Session.song_name` を照合し正解判定
4. 全回答を `Session.add_answer` で履歴蓄積、正解時のみ
   `Session.add_correct_answerer` で正解者集合へ冪等に追加
5. ephemeral で「○ 正解です」/「× 不正解です」を本人にのみ返答する
6. **公開チャンネルへの出力は無し**。セッションは終了させない
   (要件: 複数人が並行して回答できる)

楽曲名のオートコンプリートは `/play` と共通化された [src/cogs/_helpers.py](src/cogs/_helpers.py) の
`build_song_autocomplete` を利用します。`SongRepository` をクロージャに閉じ込んだ
async 関数を `answer.autocomplete("song")` 経由で登録するため、cog インスタンス生成時に
バインドが完了している必要があります。
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from src.cogs._helpers import SongAutocomplete, build_song_autocomplete
from src.core.config import get_assets_config
from src.services.session import AnswerRecord, Session
from src.services.session_manager import SessionManager
from src.services.song_repository import SongRepository

# モジュールスコープのロガー (production では `__main__` 親ロガーから propagate)
logger = logging.getLogger(__name__)


# ==================================================
# 応答メッセージ
# ==================================================
# 本人 ephemeral 応答の本文 (○/× は仕様書ステップ 5.7 に明記)
_CORRECT_MESSAGE: str = "○ 正解です"
_INCORRECT_MESSAGE: str = "× 不正解です"


# ==================================================
# /answer cog
# ==================================================
class AnswerSongCog(commands.Cog):
    """
    `/answer` スラッシュコマンドを提供する cog

    依存はコンストラクタで注入し、テスト時は mock を差し込めるようにします。
    `setup()` 関数が `Config` 経由で実装の依存を構築し、Bot に登録します。
    """

    def __init__(
        self,
        bot: commands.Bot,
        *,
        song_repository: SongRepository,
    ) -> None:
        """
        cog を初期化する

        Args:
            bot: 親 Bot インスタンス (`SDBsBot` を想定)
            song_repository: 楽曲リポジトリ (オートコンプリート / 楽曲存在チェックに使用)
        """
        super().__init__()
        self.bot: commands.Bot = bot
        self._song_repository: SongRepository = song_repository
        # `_helpers.build_song_autocomplete` で `SongRepository` をクロージャに閉じ込んだ
        # 関数を作り、後段の `answer_song_autocomplete` メソッドから委譲する。
        self._song_autocomplete: SongAutocomplete = build_song_autocomplete(
            song_repository
        )

    # --------------------------------------------------
    # スラッシュコマンド本体
    # --------------------------------------------------
    @app_commands.command(
        name="answer",
        description="パネルに隠された楽曲名を回答します (本人にのみ ○/× を返します)",
    )
    @app_commands.describe(
        song="回答する楽曲名 (部分一致で候補表示)",
    )
    async def answer(
        self,
        interaction: discord.Interaction,
        song: str,
    ) -> None:
        """
        楽曲を回答し、本人にのみ ephemeral で正解/不正解を返す

        - 公開チャンネルには結果を出さない (他メンバーには誰が何を回答したか見えない)
        - 正解しても不正解しても、セッション終了まで本人含む全員が `/play`・`/answer` を継続できる
        - 正解者は `Session.correct_answerers` に蓄積され、`/end` 時の embed に表示される
        """
        # ----- 1) 進行中セッションの確認 -----
        manager: SessionManager = SessionManager.instance()
        session: Optional[Session] = manager.current()
        if session is None:
            await interaction.response.send_message(
                "進行中のセッションがありません。/start で新しいセッションを開始してください。",
                ephemeral=True,
            )
            return

        # ----- 2) 楽曲存在チェック (autocomplete を経由しない手入力に備える) -----
        if self._song_repository.find_by_name(song) is None:
            await interaction.response.send_message(
                f"指定された楽曲が見つかりません: {song}",
                ephemeral=True,
            )
            return

        # ----- 3) 正解判定 -----
        is_correct: bool = song == session.song_name

        # ----- 4) 履歴蓄積 -----
        # `/end` の集計用に全回答 (○/×) を時系列で記録する
        session.add_answer(
            AnswerRecord(
                user_id=interaction.user.id,
                song_name=song,
                correct=is_correct,
                answered_at=datetime.now(timezone.utc),
            )
        )
        # 正解者集合への登録は冪等 (set 内部実装) のため重複登録は無害
        if is_correct:
            session.add_correct_answerer(
                user_id=interaction.user.id,
                user_name=interaction.user.display_name,
            )

        # ----- 5) ephemeral 応答 -----
        await interaction.response.send_message(
            _CORRECT_MESSAGE if is_correct else _INCORRECT_MESSAGE,
            ephemeral=True,
        )

    # --------------------------------------------------
    # オートコンプリート (instance method 形式で登録)
    # --------------------------------------------------
    @answer.autocomplete("song")
    async def _song_autocomplete_callback(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """
        楽曲名オートコンプリート

        `_helpers.build_song_autocomplete` で生成した関数へ委譲する薄いラッパ。
        cog インスタンスメソッドとして登録するため `self` を受け取る形式が必須。
        """
        return await self._song_autocomplete(interaction, current)


# ==================================================
# extension エントリポイント
# ==================================================
async def setup(bot: commands.Bot) -> None:
    """
    `Bot.load_extension` から呼ばれる cog 登録関数

    実行時の依存 (リポジトリ) を構築して cog に注入します。
    """
    assets = get_assets_config()
    song_repository = SongRepository(
        songs_json=assets.songs_json,
        images_dir=assets.images_dir,
    )

    cog = AnswerSongCog(
        bot,
        song_repository=song_repository,
    )
    await bot.add_cog(cog)
