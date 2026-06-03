import logging
import os
import time
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from src.core.config import settings


class DatedTimedRotatingFileHandler(TimedRotatingFileHandler):
    """書き込み中のファイル名にも日付を含める日次ローテーションハンドラ。

    標準の TimedRotatingFileHandler は当日分を固定名で書き込み、深夜のロールオーバー時に
    過去分へ日付を付与する。本クラスは出力先自体を `<名前>_<日付>.<拡張子>` 形式とし、
    日付が変わったら出力先を当日のファイルへ切り替える(過去分はリネームせずそのまま残す)。

    Args:
        log_dir (str): ログを格納するディレクトリ。
        file_name (str): 基準となるファイル名(例: python.log)。日付はステムと拡張子の間へ挿入する。
        backup_days (int): 保持する日次ファイルの最大数。超過分は古い順に削除する。
        encoding (str): ログファイルの文字エンコーディング。
    """

    def __init__(
        self,
        log_dir: str,
        file_name: str,
        backup_days: int,
        encoding: str = "utf-8",
    ) -> None:
        self._log_dir = Path(log_dir)
        base = Path(file_name)
        self._stem = base.stem
        self._ext = base.suffix
        super().__init__(
            self._dated_path(),
            when="midnight",
            interval=1,
            backupCount=backup_days,
            encoding=encoding,
        )

    def _dated_path(self) -> str:
        """当日の日付を挿入したログファイルのパスを返す。

        Returns:
            str: `<ディレクトリ>/<名前>_<YYYY-MM-DD>.<拡張子>` 形式のパス。
        """
        date = datetime.now().strftime("%Y-%m-%d")
        return str(self._log_dir / f"{self._stem}_{date}{self._ext}")

    def doRollover(self) -> None:
        """出力先を当日の日付ファイルへ切り替え、次回ロールオーバー時刻を再計算する。

        過去分はすでに日付入りのファイル名で確定しているため、標準ハンドラのような
        リネームは行わず、出力ストリームのみを当日のファイルへ付け替える。
        """
        if self.stream:
            self.stream.close()
        self.baseFilename = os.path.abspath(self._dated_path())
        self.stream = self._open()
        self.rolloverAt = self.computeRollover(int(time.time()))
        self._purge_old_logs()

    def _purge_old_logs(self) -> None:
        """保持数(backupCount)を超えた日次ファイルを古い順に削除する。

        日付は ISO 形式のためファイル名の昇順がそのまま古い順となる。
        """
        if self.backupCount <= 0:
            return
        files = sorted(self._log_dir.glob(f"{self._stem}_*{self._ext}"))
        for old in files[: -self.backupCount]:
            old.unlink(missing_ok=True)


def setup_logger() -> None:
    """ルートロガーへコンソール出力と日次回転ファイル出力のハンドラを設定する。

    設定値は src.core.config.settings から取得し、既存のハンドラは一度クリアされる。
    ファイル出力は当日の日付を含む名前(例: logs/python_2026-05-29.log)で行う。
    """
    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(settings.log_level)
    root.handlers.clear()

    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s: [%(filename)s-%(lineno)d] --> %(message)s"
    )

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = DatedTimedRotatingFileHandler(
        log_dir=settings.log_dir,
        file_name=settings.log_file_name,
        backup_days=settings.log_backup_days,
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
