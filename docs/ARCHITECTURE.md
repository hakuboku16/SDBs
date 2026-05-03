# アーキテクチャ設計書

本ドキュメントは Deemo × アタック25 Discord Bot の設計指針を記述する単一の参照源です。実装はこの設計に準拠して進めます。

## 目次

- [概要](#概要)
- [ゲーム進行](#ゲーム進行)
- [ディレクトリ構成](#ディレクトリ構成)
- [主要な設計判断](#主要な設計判断)
  - [セッション管理](#セッション管理)
  - [`/answer` 動作仕様](#answer-動作仕様)
  - [お題自動判定](#お題自動判定)
  - [パネル画像合成](#パネル画像合成)
  - [Cog 構造](#cog-構造)
- [設定](#設定)
- [Docker](#docker)
- [主要ファイル](#主要ファイル)
- [既存ファイルからの再利用](#既存ファイルからの再利用)
- [実装ステップ](#実装ステップ)
- [動作検証](#動作検証)


## 概要

リズムゲーム「Deemo」とクイズ番組「アタック25」を掛け合わせた Discord Bot です。

ベースは Python プロジェクトテンプレート（[src/core/config.py](src/core/config.py), [src/core/logger.py](src/core/logger.py), [src/utils/](src/utils/)）と素材（楽曲データ [assets/data/all_songs.json](assets/data/all_songs.json), お題定義 [assets/data/all_topics.json](assets/data/all_topics.json), 楽曲ジャケット画像 [assets/images/](assets/images/)）です。

技術選定:
- Discord ライブラリ: **discord.py**
- セッション保持: **インメモリのみ**（再起動で消失する前提）
- お題判定: **自動**（`PlayRecord` を全タスク条件で評価し進捗を更新）
- 画像紐付け: **楽曲名 == ファイル名（拡張子除く）**


## ゲーム進行

1. `/start` でランダムに選んだ楽曲のジャケットを N 枚（4/9/16/25）のパネルで覆い、N 個のお題と共に提示する
2. プレイヤーが Deemo をプレイし、`/play` でリザルトを入力すると、合致するお題が自動判定で進捗 +1 される
3. お題がクリアされるとパネルが1枚剥がれ、隠れた楽曲が徐々に見えてくる
4. メンバーは `/answer` で楽曲名を回答する（複数人が回答するため、`/answer` ではセッションは終了しない）
5. セッション終了条件は **「30分経過」または「`/end` 実行」の2つのみ**


## ディレクトリ構成

```
src/
├── main.py                      # Bot 起動エントリーポイント（既存を Bot 起動仕様に書き換え）
├── core/
│   ├── config.py                # 既存。Discord 関連設定モデルを追加
│   ├── logger.py                # 既存。そのまま流用
│   └── bot.py                   # NEW: discord.py の Bot サブクラス。cog 自動ロード
├── cogs/                        # NEW: 1スラッシュコマンド = 1ファイル
│   ├── __init__.py
│   ├── start_session.py         # /start
│   ├── end_session.py           # /end
│   ├── reset_session.py         # /reset
│   ├── input_play.py            # /play
│   ├── answer_song.py           # /answer
│   └── show_progress.py         # /progress
├── services/                    # ドメインロジック
│   ├── __init__.py              # 既存
│   ├── session.py               # NEW: Session, PlayRecord モデル
│   ├── session_manager.py       # NEW: シングルトン。同時1セッション保証
│   ├── task.py                  # NEW: Task モデル + ステータス
│   ├── task_generator.py        # NEW: all_topics.json から N 個ランダム生成
│   ├── task_evaluator.py        # NEW: PlayRecord をタスク条件で評価
│   ├── song_repository.py       # NEW: all_songs.json のロード/部分一致検索
│   ├── image_processor.py       # NEW: Pillow でパネル合成・回転・グレースケール・モザイク
│   └── discord_notifier.py      # NEW: ログチャンネル/結果チャンネルへの出力
└── utils/
    ├── helpers.py               # 既存
    └── validators.py            # 既存
```

ルートに `Dockerfile`, `docker-compose.yml` を追加（24h 稼働要件）。


## 主要な設計判断

### セッション管理

- `SessionManager` はクラス変数 `_current: Session | None` を保持するシングルトン
- `/start` は `_current` が存在すれば拒否（要件: 同時1セッションのみ）
- セッション開始時に `asyncio.create_task` で2本のタイマーを起動する
  - 20分後: 「残り10分」通知
  - 30分後: 自動終了（`/end` と同等処理）
- `/end` / `/reset` で両タイマーを `cancel()` する
- インメモリのみのため、Bot 再起動でセッションは消失する（許容）
- **終了条件は「30分経過」または「`/end` 実行」の2つのみ**。`/answer` の正解では終了しない

### `/answer` 動作仕様

- 回答は本人にのみ ephemeral で `○ 正解です` / `× 不正解です` を返す
- 公開チャンネルには結果を出さない（他メンバーには誰が何を回答したか見えない）
- 正解しても不正解しても、セッション終了まで本人含む全員が `/play` ・ `/answer` を継続できる
- 全回答ログ（誰が・いつ・何を回答したか）は `Session` に蓄積し、`/end` 時に結果チャンネルへ集計表示する

### お題自動判定

- `Task` は `type: str`, `set_value: int`, `value: Any`, `current: int`, `cleared: bool` を保持
- `TaskEvaluator` は `all_topics.json` の `type` ごとに評価関数を辞書登録（戦略パターン）
- `/play` 受信時、現セッションの全 `Task` に対し `evaluator.evaluate(task, play_record, all_plays)` を呼ぶ
  - True なら `current += 1`
  - `current >= set_value` で `cleared = True`
- `level_total` / `result_charming_total` / `result_combo_total` のような累積系は `all_plays` を参照
- 進捗のあったタスクのリストを `/play` のレスポンスに含める

### パネル画像合成

[src/services/image_processor.py](src/services/image_processor.py) で以下を提供:

```python
def compose(
    song_name: str,
    panel_count: int,
    cleared_indices: set[int],
    rotate: bool,
    grayscale: bool,
    mosaic_block: int,
) -> BytesIO: ...
```

処理順序:
1. 元画像を読み込む
2. `rotate` が True なら 90/180/270 度のいずれかをランダムに適用
3. `grayscale` が True ならグレースケール化
4. `mosaic_block` でモザイク処理
5. グリッド (√N × √N) でパネルを描画。`cleared_indices` のパネルは透明（剥がれた表現）

モザイク実装:

```python
image.resize((block, block), NEAREST).resize(orig_size, NEAREST)
```

`block` の値: なし=300, 弱=150, 中=90, 強=45, 最強=27（小さいほど強くかかる）。

パネルには番号を描画する（フォントは Pillow デフォルトで可）。

### Cog 構造

- 各 cog は `commands.Cog` を継承し、`@app_commands.command` でスラッシュコマンドを定義
- `Bot.setup_hook` 内で `cogs/` を自動ロード（`pkgutil.iter_modules` を利用）
- スラッシュコマンドは2サーバー両方に登録する（グローバル登録 or 両 Guild ID へ即時登録）


## 設定

### [config/settings.yaml](config/settings.yaml) への追加

```yaml
discord:
  command_sync_guilds: []     # 開発時のみ即時反映用に Guild ID を入れる。本番は空でグローバル登録
  log_channel_id: null        # エラーログ送信先
  result_channel_id: null     # セッション終了時の結果送信先
  session_timeout_minutes: 30
  warning_minutes_before_end: 10

session:
  default_panel_count: 9
  allowed_panel_counts: [4, 9, 16, 25]
  mosaic_levels:              # ラベル → block 画素数
    "なし": 300
    "弱": 150
    "中": 90
    "強": 45
    "最強": 27

assets:
  songs_json: "assets/data/all_songs.json"
  topics_json: "assets/data/all_topics.json"
  images_dir: "assets/images"
```

### `.env.example` への追加

```
DISCORD_TOKEN=
ENVIRONMENT=development
```

### `requirements.txt` への追加

- `discord.py>=2.4`
- `Pillow>=10`


## Docker

- `Dockerfile`: `python:3.13-slim` ベース、`requirements.txt` を入れて `python src/main.py`
- `docker-compose.yml`: `restart: always`、`./logs` と `./assets` をボリュームマウント、`env_file: .env`


## 主要ファイル

### 新規作成

- [src/core/bot.py](src/core/bot.py) — Bot クラス、cog ローダー、エラーハンドラ
- [src/cogs/start_session.py](src/cogs/start_session.py) — `/start`（panels, rotate, grayscale, mosaic 引数）
- [src/cogs/end_session.py](src/cogs/end_session.py) — `/end`
- [src/cogs/reset_session.py](src/cogs/reset_session.py) — `/reset`
- [src/cogs/input_play.py](src/cogs/input_play.py) — `/play`（song autocomplete, difficulty, charming, combo）
- [src/cogs/answer_song.py](src/cogs/answer_song.py) — `/answer`（song autocomplete）
- [src/cogs/show_progress.py](src/cogs/show_progress.py) — `/progress`
- [src/services/session.py](src/services/session.py)
- [src/services/session_manager.py](src/services/session_manager.py)
- [src/services/task.py](src/services/task.py)
- [src/services/task_generator.py](src/services/task_generator.py)
- [src/services/task_evaluator.py](src/services/task_evaluator.py)
- [src/services/song_repository.py](src/services/song_repository.py)
- [src/services/image_processor.py](src/services/image_processor.py)
- [src/services/discord_notifier.py](src/services/discord_notifier.py)
- `Dockerfile`, `docker-compose.yml`

### 既存ファイル変更

- [src/main.py](src/main.py) — Bot 起動処理に書き換え（環境ロード→ `Bot.run(token)`）
- [src/core/config.py](src/core/config.py) — `DiscordConfig`, `SessionConfig`, `AssetsConfig` モデルと `get_*_config` 関数を追加
- [config/settings.yaml](config/settings.yaml) — 上記 yaml ブロックを追加
- [config/settings.development.yaml](config/settings.development.yaml) — dev 用 Guild ID（任意）
- [config/settings.production.yaml](config/settings.production.yaml) — 本番用 channel id を後で記入
- [.env.example](.env.example) — `DISCORD_TOKEN=` を追加
- [requirements.txt](requirements.txt) — `discord.py`, `Pillow` を追加


## 既存ファイルからの再利用

- `get_absolute_path` / `load_yaml` / `merge_dicts` ([src/utils/helpers.py](src/utils/helpers.py)) — 全て利用
- `Config` シングルトン ([src/core/config.py:66](src/core/config.py#L66)) — `DiscordConfig` 等の追加で踏襲
- `setup_logger` ([src/core/logger.py:13](src/core/logger.py#L13)) — そのまま利用
- `is_natural_number` / `is_not_empty` ([src/utils/validators.py](src/utils/validators.py)) — `/play` の charming / combo バリデーションに利用


## 実装ステップ

要件「コードを更新したらテストコードも更新する」に従い、各ステップでテストも追加します。「1チャットごとに git にコミット」も守ります。

各ステップの状態は以下のチェックボックスで管理します。実装が完了したら `- [ ]` を `- [x]` に更新してください。

- 凡例: `- [x]` = 実装済み / `- [ ]` = 未着手

---

- [x] **ステップ 0: ARCHITECTURE.md の作成**
  - 本ドキュメントを作成し、リポジトリに永続化（本ファイル）
  - 以降の実装の単一の参照源とする

- [x] **ステップ 1: 依存と設定の土台**
  - 変更範囲が広いため以下に細分化する。各サブステップ完了時にチェックを更新する
    - [x] **1.1: 依存パッケージと環境変数**
      - [requirements.txt](requirements.txt) に `discord.py>=2.4`, `Pillow>=10` を追加
      - [.env.example](.env.example) に `DISCORD_TOKEN=` を追加
    - [x] **1.2: settings.yaml の拡張**
      - [config/settings.yaml](config/settings.yaml) に `discord` / `session` / `assets` セクションを追加（[設定](#設定)節の内容に準拠）
    - [x] **1.3: Pydantic モデル追加**
      - [src/core/config.py](src/core/config.py) に `DiscordConfig` / `SessionConfig` / `AssetsConfig` を追加
      - `Config.get_discord_config()` / `get_session_config()` / `get_assets_config()` メソッドと、対応するモジュール関数 `get_discord_config()` / `get_session_config()` / `get_assets_config()` を追加
    - [x] **1.4: テスト追加・実行**
      - [tests/core/test_config.py](tests/core/test_config.py) に新モデルのバリデーションテストと `get_*_config` のテストを追加
      - `pytest` を実行し全テストが通ることを確認

- [x] **ステップ 2: ドメインモデル（Discord 非依存）**
  - 変更範囲が広いため以下に細分化する。各サブステップ完了時にチェックを更新する。依存関係の上流から順に実施
    - [x] **2.1: 楽曲データドメイン**
      - [src/services/song_repository.py](src/services/song_repository.py): `Song` データクラス（楽曲名 / shelf / book / version / time / composer / feat / 難易度別 level・notes 辞書）と `SongRepository`（[assets/data/all_songs.json](assets/data/all_songs.json) ロード、部分一致検索、楽曲名→画像パス解決）
      - テスト: [tests/services/test_song_repository.py](tests/services/test_song_repository.py)（実 JSON を用いたロード・部分一致・画像パス解決）
    - [x] **2.2: PlayRecord と Task のモデル**
      - [src/services/session.py](src/services/session.py) に `PlayRecord`（song_name / difficulty / charming / combo）
      - [src/services/task.py](src/services/task.py) に `Task`（type / set_value / value / current / cleared）
      - いずれもロジックを最小限に留めたデータモデル
      - テスト: [tests/services/test_task.py](tests/services/test_task.py)（進捗・クリア判定の振る舞い）。`PlayRecord` の検証は 2.5 のセッションテストに含める
    - [x] **2.3: TaskGenerator**
      - [src/services/task_generator.py](src/services/task_generator.py): [assets/data/all_topics.json](assets/data/all_topics.json) から N 個ランダム生成。type の重複可否、`set` / `value` のサンプリング規則を実装
      - テスト: [tests/services/test_task_generator.py](tests/services/test_task_generator.py)
    - [x] **2.4: TaskEvaluator**
      - [src/services/task_evaluator.py](src/services/task_evaluator.py): type ごとの評価関数を辞書で保持し、`evaluate(task, play_record, all_plays, song_repo)` で判定
      - 全 type に対応（title_*, level, level_total, result_*_total, notes_*, composer_*, time_*, version, book, shelf, difficult, featuring）
      - テスト: [tests/services/test_task_evaluator.py](tests/services/test_task_evaluator.py)（type ごとの代表ケース）
    - [x] **2.5: Session と SessionManager**
      - [src/services/session.py](src/services/session.py) に `Session`（タスク / プレイ履歴 / 回答履歴 / 開始時刻 / チャンネル / 所有者など）
      - [src/services/session_manager.py](src/services/session_manager.py): シングルトン（`_current: Session | None`）。`start()` / `end()` / `reset()` / `current()` を提供
      - **タイマー処理は Discord 依存があるためステップ4以降に回し、本ステップではセッションオブジェクトの登録・取得・解放のみ実装する**
      - テスト: [tests/services/test_session.py](tests/services/test_session.py), [tests/services/test_session_manager.py](tests/services/test_session_manager.py)

- [x] **ステップ 3: 画像処理**
  - 変更範囲が広いため以下に細分化する。各サブステップ完了時にチェックを更新する
  - 全楽曲ジャケットは 300x300 RGB の前提（[assets/images/](assets/images/) を実測で確認済み）
    - [x] **3.1: ImageProcessor 骨格と単一画像エフェクト**
      - [src/services/image_processor.py](src/services/image_processor.py): `ImageProcessor` クラス（[`SongRepository`](src/services/song_repository.py) を依存注入）
      - 内部メソッドを実装: `_load_image` / `_apply_rotation`（90/180/270 ランダム） / `_apply_grayscale`（RGB のまま L→RGB に戻す） / `_apply_mosaic`（resize→resize 方式）
      - 効果適用順序は [パネル画像合成](#パネル画像合成)節に準拠
      - テスト: [tests/services/test_image_processor.py](tests/services/test_image_processor.py)（各エフェクトの単独適用・出力サイズ・モード）
    - [x] **3.2: パネルグリッド合成**
      - 内部メソッド `_overlay_panels(image, panel_count, cleared_indices) -> Image` を実装
      - `cleared_indices` のセルは加工せず、それ以外のセルは不透明な矩形で覆い、中央に番号（1-origin）を描画
      - フォントは Pillow のデフォルト（`ImageFont.load_default()`）を使用
      - テスト: cleared セル中央のピクセルが元画像と等しい、非 cleared セル中央のピクセルがパネル色と等しいこと
    - [x] **3.3: compose 統合**
      - `compose(song_name, panel_count, cleared_indices, rotate, grayscale, mosaic_block) -> BytesIO` を公開メソッドとして実装
      - 入力バリデーション: `panel_count` は平方数、`mosaic_block` は正、`cleared_indices` は `[0, panel_count)` 範囲内、楽曲名は SongRepository に存在
      - 出力は PNG 形式の `BytesIO`（discord.py の `discord.File` に直接渡せる形）
      - テスト: 出力 PNG サイズが元画像と一致、cleared 指定枚数分のパネルだけが剥がれていること、エラーケース（不正引数）

- [ ] **ステップ 4: Bot とログ通知基盤**
  - `src/core/bot.py`（cog 自動ロード、`on_app_command_error` で Discord ログチャンネルへ送信）
  - `services/discord_notifier.py`
  - `src/main.py` を Bot 起動仕様に変更

- [ ] **ステップ 5: Cog 実装（1コマンドずつ）**
  - 全コマンドを単一のチェックボックスでまとめず、コマンドごとに進捗を可視化:
    - [ ] `/start`（[src/cogs/start_session.py](src/cogs/start_session.py)）
    - [ ] `/progress`（[src/cogs/show_progress.py](src/cogs/show_progress.py)）
    - [ ] `/play`（[src/cogs/input_play.py](src/cogs/input_play.py)）
    - [ ] `/answer`（[src/cogs/answer_song.py](src/cogs/answer_song.py)）
    - [ ] `/end`（[src/cogs/end_session.py](src/cogs/end_session.py)）
    - [ ] `/reset`（[src/cogs/reset_session.py](src/cogs/reset_session.py)）
  - 各 cog 追加時にエンドツーエンドの想定動作を README/DEVELOPMENT.md に追記

- [ ] **ステップ 6: Docker 化**
  - `Dockerfile` と `docker-compose.yml`
  - `docker compose up --build` で 24h 稼働確認


## 動作検証

### 単体テスト

- `pytest`（既存設定: [pytest.ini](pytest.ini) で `--cov=src`）
- 追加対象: `tests/services/test_*.py`, `tests/cogs/test_*.py`（cog は `discord.ext.test` か mock を使用）
- 既存テスト（[tests/test_main.py](tests/test_main.py), [tests/core/](tests/core/), [tests/utils/](tests/utils/)）は main.py 変更に追従して更新

### 結合テスト（手動）

1. テストサーバーで `.env` に `DISCORD_TOKEN` を設定し `python src/main.py` 起動
2. `/start panels:4 mosaic:中` → ピン留め確認、パネル4枚の画像表示確認
3. `/play song:Aya difficulty:Hard charming:300 combo:300` → 該当タスクが進捗 +1 されパネルが剥がれることを確認
4. `/progress` → タスク状態の表示確認
5. `/answer song:Aya` → 本人にのみ ephemeral で ○/× が返ることを確認。正解後も `/play` ・ `/answer` を続けられることを確認。複数メンバーが並行して回答できることを確認
6. `/end` → 全員の回答ログを集計表示・結果チャンネルへマスク済み楽曲名で投稿・ピン解除
7. 30分タイマー（`session_timeout_minutes` を一時的に 1 にして検証） → 10分前通知 → 自動終了
8. エラーを意図的に発生（不正な楽曲名）→ ログチャンネル投稿確認

### Docker 検証

```bash
docker compose up --build -d
docker compose logs -f
```

コンテナが落ちた際 `restart: always` で復帰することを確認。
