"""
discord_notifier.py のユニットテスト

`DiscordNotifier` の以下の振る舞いを検証します:
    - エラー通知 (例外ありなし、長文の切り詰め)
    - セッション結果通知 (添付ファイル付き送信)
    - 異常系 (チャンネル ID 未設定、`get_channel` が None、send 不可型、Discord 例外発生)

`discord.Client` は本物を起動せず `MagicMock(spec=discord.Client)` で差し替え、
チャンネルや send は `AsyncMock` でモックします。
"""

import asyncio
import logging
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from src.core.config import DiscordConfig
from src.services.discord_notifier import DiscordNotifier


# ==================================================
# 共通ヘルパー
# ==================================================
def _make_config(
    log_channel_id: int | None = 100,
    result_channel_id: int | None = 200,
) -> DiscordConfig:
    """
    テスト用の `DiscordConfig` を組み立てる
    """
    return DiscordConfig(
        log_channel_id=log_channel_id,
        result_channel_id=result_channel_id,
    )


def _make_client_with_text_channel(channel_id_to_channel: dict[int, object]) -> MagicMock:
    """
    `get_channel` が辞書ベースで応答するモック discord.Client を返す

    Args:
        channel_id_to_channel: チャンネル ID → モックチャンネル の辞書。
            指定外の ID は None を返す (実 discord.Client の挙動と同じ)
    """
    client: MagicMock = MagicMock(spec=discord.Client)
    client.get_channel = MagicMock(side_effect=lambda cid: channel_id_to_channel.get(cid))
    return client


def _make_async_send_channel() -> MagicMock:
    """
    `send` が AsyncMock として呼べるテキスト系チャンネルのモックを返す
    """
    channel: MagicMock = MagicMock()
    channel.send = AsyncMock()
    return channel


def _run(coro) -> None:
    """asyncio.run の薄いラッパ (テスト見通し向上のため)"""
    asyncio.run(coro)


# ==================================================
# notify_error: 正常系
# ==================================================
class TestNotifyError:
    """`notify_error` の振る舞い"""

    def test_sends_message_only_when_no_exception(self):
        """例外を渡さない場合は本文だけが embed の description に格納されて送られる"""
        channel = _make_async_send_channel()
        client = _make_client_with_text_channel({100: channel})
        notifier = DiscordNotifier(client, _make_config())

        _run(notifier.notify_error("ハンドラで未捕捉のエラー"))

        client.get_channel.assert_called_once_with(100)
        channel.send.assert_awaited_once()
        kwargs = channel.send.await_args.kwargs
        # Bot からの送信は embed 統一なので content は空、embed が渡る
        assert kwargs.get("content") == ""
        embed = kwargs.get("embed")
        assert isinstance(embed, discord.Embed)
        assert embed.description == "ハンドラで未捕捉のエラー"

    def test_sends_traceback_when_exception_provided(self):
        """例外を渡すと traceback がコードブロックで embed の description に付加される"""
        channel = _make_async_send_channel()
        client = _make_client_with_text_channel({100: channel})
        notifier = DiscordNotifier(client, _make_config())

        try:
            raise RuntimeError("テスト例外")
        except RuntimeError as exc:
            _run(notifier.notify_error("発生箇所: /play", exc=exc))

        channel.send.assert_awaited_once()
        embed = channel.send.await_args.kwargs["embed"]
        sent: str = embed.description or ""
        assert "発生箇所: /play" in sent
        assert "RuntimeError" in sent
        assert "テスト例外" in sent
        # traceback はコードブロック内に出力される
        assert "```" in sent

    def test_truncates_overly_long_content(self):
        """4096 文字を超える本文は embed.description が切り詰められ、末尾 (発生箇所側) が残る"""
        channel = _make_async_send_channel()
        client = _make_client_with_text_channel({100: channel})
        notifier = DiscordNotifier(client, _make_config())

        # 末尾近くに目印を置き、それが残ることを確認する
        long_message = "X" * 5000 + "MARKER_AT_TAIL"
        _run(notifier.notify_error(long_message))

        embed = channel.send.await_args.kwargs["embed"]
        sent: str = embed.description or ""
        # embed.description の上限 (4096) を超えない
        assert len(sent) <= 4096
        assert sent.endswith("MARKER_AT_TAIL")
        # 切り詰めマーカーが先頭側に挿入される
        assert "切り詰め" in sent


# ==================================================
# notify_session_result: 正常系
# ==================================================
class TestNotifySessionResult:
    """`notify_session_result` の振る舞い"""

    def test_sends_embed_with_spoiler_song_in_description_and_image_attachment(self):
        """
        スポイラー楽曲名を embed.description に、合成画像を添付 + embed.image として送る

        embed.title はスポイラー記法を描画しないため、楽曲名は description 側に出す。
        """
        channel = _make_async_send_channel()
        client = _make_client_with_text_channel({200: channel})
        notifier = DiscordNotifier(client, _make_config())

        # 中身は何でもよい (Discord 側送信は AsyncMock で握り潰される)
        image = BytesIO(b"\x89PNG\r\n\x1a\nfake")
        _run(
            notifier.notify_session_result(
                image=image,
                spoiler_song_name="||Magnolia            ||",
                correct_answerers=[(1, "alice"), (2, "bob")],
                summary="セッション終了",
            )
        )

        client.get_channel.assert_called_once_with(200)
        channel.send.assert_awaited_once()
        kwargs = channel.send.await_args.kwargs

        # embed が渡される
        embed = kwargs["embed"]
        assert isinstance(embed, discord.Embed)
        # title は固定文言、楽曲名は description にスポイラーで載る
        assert embed.title == "🎵 セッション結果"
        assert embed.description is not None
        assert "セッション終了" in embed.description
        assert "||Magnolia            ||" in embed.description
        # embed.image.url は attachment スキーム
        assert embed.image.url == "attachment://session_result.png"
        # 正解者 field が含まれる
        fields = {f.name: f.value or "" for f in embed.fields}
        assert "正解者" in fields
        assert "alice" in fields["正解者"]
        assert "bob" in fields["正解者"]

        # 添付ファイルは discord.File で渡る
        assert isinstance(kwargs["file"], discord.File)
        assert kwargs["file"].filename == "session_result.png"

    def test_shows_no_answerers_label_when_empty(self):
        """正解者が 0 件の場合は「正解者なし」と表示する"""
        channel = _make_async_send_channel()
        client = _make_client_with_text_channel({200: channel})
        notifier = DiscordNotifier(client, _make_config())

        _run(
            notifier.notify_session_result(
                image=BytesIO(b"x"),
                spoiler_song_name="||short               ||",
                correct_answerers=set(),
            )
        )

        embed = channel.send.await_args.kwargs["embed"]
        fields = {f.name: f.value for f in embed.fields}
        assert fields["正解者"] == "正解者なし"

    def test_sorts_answerers_by_user_name(self):
        """``set`` 入力でも user_name 昇順で安定表示する"""
        channel = _make_async_send_channel()
        client = _make_client_with_text_channel({200: channel})
        notifier = DiscordNotifier(client, _make_config())

        _run(
            notifier.notify_session_result(
                image=BytesIO(b"x"),
                spoiler_song_name="||short               ||",
                correct_answerers={(3, "charlie"), (1, "alice"), (2, "bob")},
            )
        )

        embed = channel.send.await_args.kwargs["embed"]
        value = next(f.value or "" for f in embed.fields if f.name == "正解者")
        # alice → bob → charlie の順に並ぶ
        assert value.index("alice") < value.index("bob") < value.index("charlie")


# ==================================================
# 異常系 (送信スキップ・警告ログ)
# ==================================================
class TestSkipsAndWarnings:
    """送信できない条件下では送信をスキップし warning を残す"""

    def test_skips_when_log_channel_id_not_set(self, caplog: pytest.LogCaptureFixture):
        """`log_channel_id` が None なら送信せず warning"""
        client = _make_client_with_text_channel({})
        notifier = DiscordNotifier(client, _make_config(log_channel_id=None))

        with caplog.at_level(logging.WARNING, logger="src.services.discord_notifier"):
            _run(notifier.notify_error("メッセージ"))

        client.get_channel.assert_not_called()
        assert any("ログチャンネル ID が未設定" in rec.message for rec in caplog.records)

    def test_skips_when_result_channel_id_not_set(self, caplog: pytest.LogCaptureFixture):
        """`result_channel_id` が None なら送信せず warning"""
        client = _make_client_with_text_channel({})
        notifier = DiscordNotifier(client, _make_config(result_channel_id=None))

        with caplog.at_level(logging.WARNING, logger="src.services.discord_notifier"):
            _run(
                notifier.notify_session_result(
                    image=BytesIO(b"x"),
                    spoiler_song_name="||short               ||",
                    correct_answerers=[],
                    summary="dummy",
                )
            )

        client.get_channel.assert_not_called()
        assert any("結果チャンネル ID が未設定" in rec.message for rec in caplog.records)

    def test_skips_when_get_channel_returns_none(self, caplog: pytest.LogCaptureFixture):
        """`get_channel` が None を返すと送信スキップ + warning"""
        # ID 999 は辞書に無いので get_channel は None を返す
        client = _make_client_with_text_channel({})
        notifier = DiscordNotifier(client, _make_config(log_channel_id=999))

        with caplog.at_level(logging.WARNING, logger="src.services.discord_notifier"):
            _run(notifier.notify_error("メッセージ"))

        client.get_channel.assert_called_once_with(999)
        assert any("取得できませんでした" in rec.message for rec in caplog.records)

    def test_skips_when_channel_has_no_send(self, caplog: pytest.LogCaptureFixture):
        """`send` を持たないチャンネル (例: カテゴリ) ではスキップ + warning"""
        # send 属性のないオブジェクト
        no_send_channel = object()
        client = _make_client_with_text_channel({100: no_send_channel})
        notifier = DiscordNotifier(client, _make_config(log_channel_id=100))

        with caplog.at_level(logging.WARNING, logger="src.services.discord_notifier"):
            _run(notifier.notify_error("メッセージ"))

        assert any("send をサポートしていません" in rec.message for rec in caplog.records)

    def test_warns_when_send_raises_discord_exception(
        self, caplog: pytest.LogCaptureFixture
    ):
        """`send` が `discord.DiscordException` を投げた場合は握って warning"""
        channel = MagicMock()
        channel.send = AsyncMock(side_effect=discord.DiscordException("送信失敗"))
        client = _make_client_with_text_channel({100: channel})
        notifier = DiscordNotifier(client, _make_config(log_channel_id=100))

        with caplog.at_level(logging.WARNING, logger="src.services.discord_notifier"):
            _run(notifier.notify_error("メッセージ"))

        channel.send.assert_awaited_once()
        assert any("送信に失敗しました" in rec.message for rec in caplog.records)

    def test_propagates_non_discord_exceptions(self):
        """Discord 以外の例外は握らず呼び出し側に伝播させる"""
        channel = MagicMock()
        channel.send = AsyncMock(side_effect=RuntimeError("想定外"))
        client = _make_client_with_text_channel({100: channel})
        notifier = DiscordNotifier(client, _make_config(log_channel_id=100))

        with pytest.raises(RuntimeError, match="想定外"):
            _run(notifier.notify_error("メッセージ"))
