"""
cog 用テストパッケージ

ここに配置されるテストは [src/cogs/](../../src/cogs/) 配下の各スラッシュコマンド
モジュールに対応します。Discord ライブラリ全体を起動せず、
[`tests/cogs/conftest.py`](conftest.py) の Interaction mock ヘルパーで
最小限の振る舞いだけを差し替えてテストします。
"""
