import logging

from src.bot.discord_log_handler import should_forward


def _record(name: str, level: int) -> logging.LogRecord:
    """テスト用の LogRecord を組み立てる。

    Args:
        name: ロガー名。
        level: ログレベル数値。

    Returns:
        logging.LogRecord: 指定名・レベルのレコード。
    """
    return logging.LogRecord(
        name=name,
        level=level,
        pathname=__file__,
        lineno=1,
        msg="m",
        args=(),
        exc_info=None,
    )


def test_forwards_warning_from_app_logger() -> None:
    """しきい値以上かつアプリ由来のレコードは転送対象になる。"""
    record = _record("src.cogs.session_start", logging.WARNING)
    assert should_forward(record, logging.WARNING) is True


def test_excludes_below_threshold() -> None:
    """しきい値未満のレコードは転送対象外になる。"""
    record = _record("src.app", logging.INFO)
    assert should_forward(record, logging.WARNING) is False


def test_excludes_discord_library_records() -> None:
    """discord ライブラリ由来のレコードはループ防止のため転送対象外になる。"""
    record = _record("discord.gateway", logging.ERROR)
    assert should_forward(record, logging.WARNING) is False
