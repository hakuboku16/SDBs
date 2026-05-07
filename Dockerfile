# =============================================================================
# Deemo x アタック25 Discord Bot コンテナイメージ
# =============================================================================
# - 24h 稼働を前提とした軽量 Python ランタイム
# - requirements.txt を先にコピーすることで、依存解決レイヤをキャッシュする
# - 非 root ユーザー (app) で実行する
# =============================================================================

FROM python:3.13-slim

# Python の標準的な実行環境設定
#   PYTHONDONTWRITEBYTECODE: .pyc を生成しない (コンテナで不要)
#   PYTHONUNBUFFERED:        stdout/stderr を即時フラッシュ (ログ可視性)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 依存パッケージのインストール
# requirements.txt のみを先にコピーすることで、ソース変更時のキャッシュヒット率を上げる
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーション本体のコピー
COPY src ./src
COPY config ./config
COPY assets ./assets

# 実行時に書き込むディレクトリを用意 (docker-compose で host にマウントされる前提)
RUN mkdir -p /app/logs

# 非 root ユーザーで実行する (ハードニング)
RUN useradd --create-home --shell /usr/sbin/nologin app && \
    chown -R app:app /app
USER app

# Bot 起動エントリーポイント
CMD ["python", "src/main.py"]
