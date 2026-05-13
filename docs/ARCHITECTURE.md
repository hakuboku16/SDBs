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
  - [Bot 応答 embed](#bot-応答-embed)
  - [結果通知](#結果通知)
- [設定](#設定)
- [Docker](#docker)
- [主要ファイル](#主要ファイル)
- [既存ファイルからの再利用](#既存ファイルからの再利用)
- [実装ステップ](#実装ステップ)
- [動作検証](#動作検証)


## 概要

リズムゲーム「Deemo」とクイズ番組「アタック25」を掛け合わせた Discord Bot です。

ベースは Python プロジェクトテンプレート ([src/core/config.py](../src/core/config.py), [src/core/logger.py](../src/core/logger.py), [src/utils/](../src/utils/)) と素材 (楽曲データ [assets/data/all_songs.json](../assets/data/all_songs.json), お題定義 [assets/data/all_topics.json](../assets/data/all_topics.json), 楽曲ジャケット画像 [assets/images/](../assets/images/)) です。

技術選定:
- Discord ライブラリ: **discord.py**
- セッション保持: **インメモリのみ** (再起動で消失する前提)
- お題判定: **自動** (`PlayRecord` を全タスク条件で評価し進捗を更新)
- 画像紐付け: **楽曲名 == ファイル名 (拡張子除く)**


## ゲーム進行

1. `/start` でランダムに選んだ楽曲のジャケットを N 枚 (4/9/16/25) のパネルで覆い、N 個のお題と共に提示する。投稿メッセージはピン留めする
2. プレイヤーが Deemo をプレイし、`/play` でリザルトを入力すると、合致するお題が自動判定で進捗 +1 される
3. お題がクリアされるとパネルが 1 枚剥がれ、隠れた楽曲が徐々に見えてくる
4. メンバーは `/answer` で楽曲名を回答する (複数人が回答するため、`/answer` ではセッションは終了しない)
5. セッション終了条件は **「30 分経過」または「`/end` 実行」の 2 つのみ**
6. 終了時は結果チャンネルへスポイラー楽曲名 / 最終パネル画像 / 正解者一覧の embed を投稿する


## ディレクトリ構成

```
src/
├── main.py                      # Bot 起動エントリーポイント
├── core/
│   ├── config.py                # YAML + Pydantic モデル (DiscordConfig / SessionConfig / AssetsConfig)
│   ├── logger.py                # ログ管理
│   └── bot.py                   # SDBsBot (cog 自動ロード・コマンド同期・on_app_command_error)
├── cogs/                        # 1 スラッシュコマンド = 1 ファイル
│   ├── __init__.py
│   ├── _helpers.py              # 楽曲名 autocomplete + 用途別 embed ビルダ + build_topic_field
│   ├── start_session.py         # /start
│   ├── end_session.py           # /end
│   ├── reset_session.py         # /reset
│   ├── input_play.py            # /play
│   ├── answer_song.py           # /answer
│   └── show_progress.py         # /progress
├── services/                    # ドメインロジック (原則 Discord 非依存)
│   ├── __init__.py
│   ├── session.py               # Session / PlayRecord / AnswerRecord
│   ├── session_manager.py       # シングルトン + タイマー (asyncio.create_task)
│   ├── session_finalizer.py     # /end と自動タイムアウトの共通終了処理
│   ├── task.py                  # Task モデル (play_quality 含む) + 進捗更新
│   ├── task_generator.py        # all_topics.json から N 個ランダム生成
│   ├── task_evaluator.py        # type ごとの評価関数 (戦略パターン)
│   ├── song_repository.py       # all_songs.json ロード + 部分一致検索
│   ├── image_processor.py       # Pillow でパネル合成・回転・グレースケール・モザイク
│   └── discord_notifier.py      # ログ / 結果チャンネルへの送信
└── utils/
    ├── helpers.py               # ファイル I/O 等
    └── validators.py            # バリデーション関数
```

ルートに `Dockerfile`, `docker-compose.yml` を配置 (24h 稼働要件)。
プレイヤー向け説明は [README.md](../README.md)、ローカル導入手順は [DEVELOPMENT.md](DEVELOPMENT.md) を参照。


## 主要な設計判断

### セッション管理

- `SessionManager` はクラス変数 `_current: Session | None` を保持するシングルトン
- `/start` は `_current` が存在すれば拒否 (要件: 同時 1 セッションのみ)
- セッション開始時に `asyncio.create_task` で 2 本のタイマーを起動する
  - 警告タイマー (既定: 開始 20 分後) → `on_warning` で「残り 10 分」通知を進行チャンネルへ送信
  - 終了タイマー (既定: 開始 30 分後) → `on_timeout` で「制限時間が終了しました」を進行チャンネルへ送信したのち、`SessionFinalizer.finalize` を呼び結果チャンネルへ embed を投稿
- `/end` / `/reset` で両タイマーを `cancel()` する
- 遅延値 (秒) は呼び出し側 cog で `DiscordConfig.session_timeout_minutes` / `warning_minutes_before_end` から算出して `start()` に注入する (manager 自身は config に依存しない設計)
- インメモリのみのため、Bot 再起動でセッションは消失する (許容)
- **終了条件は「30 分経過」または「`/end` 実行」の 2 つのみ**。`/answer` の正解では終了しない
- 手動 `/end` と自動タイムアウトの終了後処理は [`SessionFinalizer`](../src/services/session_finalizer.py) で共通化し、`SessionManager.is_active()` で冪等性を担保 (二重呼び出し時は no-op)

### `/answer` 動作仕様

- 回答は本人にのみ ephemeral で `🎉 正解です！` (success embed) / `❌ 不正解です` (error embed) を返す
- 公開チャンネルには結果を出さない (他メンバーには誰が何を回答したか見えない)
- 正解しても不正解しても、セッション終了まで本人含む全員が `/play` ・ `/answer` を継続できる
- 正解者 (user_id / user_name のセット、重複排除) を `Session.correct_answerers` に蓄積し、`/end` 時に結果チャンネル embed の正解者欄として表示する
- 回答履歴 (`AnswerRecord`) は `Session.answer_records` に時系列で蓄積する (`/end` 集計用)

### お題自動判定

- `Task` は以下のフィールドを保持する
  - `type: str` — お題種別 (例: `title_include`, `level_total`)
  - `set_value: int` — クリアまでに必要な達成回数
  - `value: Any` — お題ごとに固有のパラメータ (list / int / float / None)
  - `play_quality: Literal["AC", "FC", "プレイ"]` — カウント対象とするプレイ品質
  - `description_template: str` — `all_topics.json` 由来の placeholder 入りテキスト
  - `current: int` / `cleared: bool`
- [`TaskGenerator`](../src/services/task_generator.py) は `play_quality` を **AC=1 / FC=3 / プレイ=6 の重み付き抽選** で決定する
- [`TaskEvaluator`](../src/services/task_evaluator.py) は `type` ごとに評価関数を辞書登録 (戦略パターン)
- `/play` 受信時、現セッションの全 `Task` に対し `evaluator.evaluate(task, play_record, all_plays, song_repo)` を呼ぶ
  - `_satisfies_quality` で `play_record` がタスクの `play_quality` (AC: charming==NOTES / FC: combo==NOTES / プレイ: 常に True) を満たすか先に判定し、満たさなければ現 `current` を返して進捗を停止
  - マッチ系: 条件成立で `current + 1`、不成立で据え置き
  - 累積系 (`level_total` / `result_charming_total` / `result_combo_total`): `all_plays` を品質フィルタで絞り込んでから合計値を再計算 (`level_total` では文字列レベルの Ex 譜面はスキップ)
- 返値を `Task.set_progress(new_current)` で反映する。`set_value` 到達で `cleared = True`
- 進捗のあったタスクと「新規 cleared」を `/play` のレスポンスに含める
- description 表示は `Task.format_description()` で placeholder (`value` / `set` / `play`) を実値に置換する

### パネル画像合成

[src/services/image_processor.py](../src/services/image_processor.py) で以下を提供。

```python
def pick_rotation_angle() -> int: ...           # 0/90/180/270 度のいずれかを返す

def compose(
    song_name: str,
    panel_count: int,
    cleared_indices: set[int],
    rotation_angle: Optional[int],
    grayscale: bool,
    mosaic_block: int,
) -> BytesIO: ...
```

処理順序:
1. 元画像を読み込む (300×300 RGB を前提)
2. `rotation_angle` が指定されていればその角度で回転 (`None` ならスキップ)
3. `grayscale=True` ならグレースケール化 (L→RGB に戻して後段の合成と整合)
4. `mosaic_block` でモザイク処理 (`block` 画素まで縮小 → NEAREST で元サイズへ拡大)
5. グリッド (√N × √N) でパネルを描画。`cleared_indices` のセルは未塗装 (= 元画像が見える)、それ以外は塗りつぶし + 番号描画 (1-origin)

**回転角度はセッション開始時に 1 度だけ決め、以降の再合成では同じ角度を再利用する。**
[`StartSessionCog`](../src/cogs/start_session.py) が `pick_rotation_angle()` を呼び `Session.rotation_angle` に格納し、`/play` のパネルめくり再合成や `SessionFinalizer` の結果画像でも同じ値を渡す。`_ROTATE_CHOICES` には `0` を含めることで「回転オプション有効でも見た目は元のまま」を許容する。

モザイク実装:

```python
image.resize((block, block), NEAREST).resize(orig_size, NEAREST)
```

`block` の値: なし=300, 弱=150, 中=90, 強=45, 最強=27 (小さいほど強くかかる)。

パネルには番号を描画する (フォントは `ImageFont.load_default()`)。

### Cog 構造

- 各 cog は `commands.Cog` を継承し、`@app_commands.command` でスラッシュコマンドを定義
- `Bot.setup_hook` 内で `cogs/` を自動ロード (`pkgutil.iter_modules` を利用)
- アンダースコア始まりモジュール (`_helpers.py`) は cog 本体ではないヘルパー扱いとし、ローダーで除外する
- 共通ヘルパー [src/cogs/\_helpers.py](../src/cogs/_helpers.py) には以下を集約する
  - `build_song_autocomplete(repository)` — 楽曲名部分一致オートコンプリート関数のファクトリ
  - `build_info_embed` / `build_success_embed` / `build_warning_embed` / `build_error_embed` — 用途別 embed ビルダ
  - `build_topic_field(index, task)` — お題 1 件を `(field_name, field_value)` に整形 (`/start` / `/play` / `/progress` で共有)
- スラッシュコマンドは 2 サーバー両方に登録する (グローバル登録 or 両 Guild ID へ即時登録)
- スラッシュコマンドで未捕捉の例外は `SDBsBot.on_app_command_error` がログチャンネルへ traceback 付き embed で送信し、ユーザーには ephemeral の error embed を返す

### Bot 応答 embed

Bot からの送信はすべて **embed 形式** に統一する。色分けと用途は以下のとおり (要件: 「Bot が送信するメッセージはすべて embed 形式」)。

| 種別    | 色      | 主な利用シーン                                                 |
| :------ | :------ | :------------------------------------------------------------- |
| 情報    | blurple | `/start` のセッション情報・お題一覧、`/progress` 表示          |
| 成功    | green   | `/play` の進捗応答、`/answer` の正解、`/end` の完了応答         |
| 警告    | orange  | 残り 10 分前通知、制限時間終了通知、`/play` の上限超過拒否     |
| エラー  | red     | バリデーション失敗、`/answer` の不正解、`on_app_command_error` |

`/play` は楽曲・難易度・charming / combo の上限 (= ノーツ数) を超えた入力を warning embed で ephemeral 拒否し、`PlayRecord` 追加・タスク評価は行わない。

進捗表示は `[✅/⬜] パネル {index} ({current}/{set_value})` を field 名に、`Task.format_description()` の結果を field value に置く。

### 結果通知

`/end` または自動タイムアウト時に [`SessionFinalizer.finalize`](../src/services/session_finalizer.py) が以下を実施する。

1. 現状のクリア状況を反映した最終画像を `ImageProcessor.compose` で再合成 (合成失敗時は warning ログのみで通知をスキップ)
2. `DiscordNotifier.notify_session_result` で結果チャンネルへ embed を投稿
   - **title**: `🎵 セッション結果` (固定)
   - **description**: 終了種別 (`セッション終了` / `セッション終了 (時間切れ)`) と楽曲名 (スポイラー記法 `||...||`)
     - 楽曲名は `_SPOILER_MIN_WIDTH=20` 文字まで右側スペースパディングし、短い名前で文字数が見抜かれないようにする
   - **image**: 最終パネル画像 (回転 / グレースケール / モザイクは開始時の設定を維持)
   - **field "正解者"**: `Session.correct_answerers` を `user_name` 昇順にソートして列挙。0 件なら `正解者なし`
3. `session.pinned_message_id` が存在すればピン解除
4. `SessionManager.end()` でセッション破棄 + タイマー停止

`/reset` は本 finalizer を経由せず、ピン解除と `SessionManager.reset()` のみ実行する (結果チャンネル投稿なし)。


## 設定

### [config/settings.yaml](../config/settings.yaml) 構成

```yaml
discord:
  command_sync_guilds: []     # 開発時のみ即時反映用に Guild ID を入れる。本番は空でグローバル登録
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

> **チャンネル ID (ログ送信先 / 結果送信先) は yaml ではなく `.env` で管理する。**
> 環境ごとにサーバー構成が変わる前提のため、`get_discord_config()` が起動時に環境変数を読み込んで `DiscordConfig.log_channel_id` / `result_channel_id` に注入する (整数として解釈できない値は `ValueError`)。

### `.env.example` への追加

```
DISCORD_TOKEN=
ENVIRONMENT=development
LOG_CHANNEL_ID=
RESULT_CHANNEL_ID=
```

### `requirements.txt` への追加

- `discord.py>=2.4`
- `Pillow>=10`


## Docker

- `Dockerfile`: `python:3.13-slim` ベース、非 root ユーザー `app` で `python src/main.py` を起動
- `docker-compose.yml`: `restart: always`、`./logs` と `./assets` をボリュームマウント、`env_file: .env`、`healthcheck` で Python プロセス生存確認


## 主要ファイル

- [src/main.py](../src/main.py) — Bot 起動エントリ。`.env` ロード → 環境決定 → ロガー初期化 → `SDBsBot.run(token)`
- [src/core/bot.py](../src/core/bot.py) — `SDBsBot`、cog ローダー、`on_app_command_error`
- [src/core/config.py](../src/core/config.py) — `DiscordConfig` / `SessionConfig` / `AssetsConfig` モデルと `get_*_config` 関数
- [src/cogs/_helpers.py](../src/cogs/_helpers.py) — autocomplete / embed ビルダ / お題 field 整形の共通関数
- [src/cogs/start_session.py](../src/cogs/start_session.py) — `/start` (panels, rotate, grayscale, mosaic)
- [src/cogs/end_session.py](../src/cogs/end_session.py) — `/end`
- [src/cogs/reset_session.py](../src/cogs/reset_session.py) — `/reset`
- [src/cogs/input_play.py](../src/cogs/input_play.py) — `/play` (song autocomplete, difficulty, charming, combo)
- [src/cogs/answer_song.py](../src/cogs/answer_song.py) — `/answer` (song autocomplete)
- [src/cogs/show_progress.py](../src/cogs/show_progress.py) — `/progress`
- [src/services/session.py](../src/services/session.py) — `Session` / `PlayRecord` / `AnswerRecord`
- [src/services/session_manager.py](../src/services/session_manager.py) — シングルトン + タイマー
- [src/services/session_finalizer.py](../src/services/session_finalizer.py) — `/end` と自動タイムアウトの共通終了処理
- [src/services/task.py](../src/services/task.py) — `Task` モデル (`play_quality` 含む)
- [src/services/task_generator.py](../src/services/task_generator.py) — お題ランダム生成
- [src/services/task_evaluator.py](../src/services/task_evaluator.py) — type ごとの評価関数 (戦略パターン)
- [src/services/song_repository.py](../src/services/song_repository.py) — 楽曲リポジトリ
- [src/services/image_processor.py](../src/services/image_processor.py) — Pillow 画像処理
- [src/services/discord_notifier.py](../src/services/discord_notifier.py) — ログ / 結果通知ラッパ
- `Dockerfile`, `docker-compose.yml`


## 既存ファイルからの再利用

- `get_absolute_path` / `load_yaml` / `merge_dicts` ([src/utils/helpers.py](../src/utils/helpers.py)) — 全て利用
- `Config` シングルトン ([src/core/config.py](../src/core/config.py)) — `DiscordConfig` 等の追加で踏襲
- `setup_logger` ([src/core/logger.py](../src/core/logger.py)) — そのまま利用
- `is_natural_number` / `is_not_empty` ([src/utils/validators.py](../src/utils/validators.py)) — `/play` の charming / combo バリデーションに利用


## 実装ステップ

要件「コードを更新したらテストコードも更新する」に従い、各ステップでテストも追加します。「1 チャットごとに git にコミット」も守ります。

各ステップの状態は以下のチェックボックスで管理します。実装が完了したら `- [ ]` を `- [x]` に更新してください。

- 凡例: `- [x]` = 実装済み / `- [ ]` = 未着手

---

- [x] **ステップ 0: ARCHITECTURE.md の作成**
  - 本ドキュメントを作成し、リポジトリに永続化 (本ファイル)
  - 以降の実装の単一の参照源とする

- [x] **ステップ 1: 依存と設定の土台**
  - 変更範囲が広いため以下に細分化する。各サブステップ完了時にチェックを更新する
    - [x] **1.1: 依存パッケージと環境変数**
      - [requirements.txt](../requirements.txt) に `discord.py>=2.4`, `Pillow>=10` を追加
      - [.env.example](../.env.example) に `DISCORD_TOKEN=` を追加
    - [x] **1.2: settings.yaml の拡張**
      - [config/settings.yaml](../config/settings.yaml) に `discord` / `session` / `assets` セクションを追加 ([設定](#設定) 節の内容に準拠)
    - [x] **1.3: Pydantic モデル追加**
      - [src/core/config.py](../src/core/config.py) に `DiscordConfig` / `SessionConfig` / `AssetsConfig` を追加
      - `Config.get_discord_config()` / `get_session_config()` / `get_assets_config()` メソッドと、対応するモジュール関数 `get_discord_config()` / `get_session_config()` / `get_assets_config()` を追加
    - [x] **1.4: テスト追加・実行**
      - [tests/core/test_config.py](../tests/core/test_config.py) に新モデルのバリデーションテストと `get_*_config` のテストを追加
      - `pytest` を実行し全テストが通ることを確認

- [x] **ステップ 2: ドメインモデル (Discord 非依存)**
  - 変更範囲が広いため以下に細分化する。各サブステップ完了時にチェックを更新する。依存関係の上流から順に実施
    - [x] **2.1: 楽曲データドメイン**
      - [src/services/song_repository.py](../src/services/song_repository.py): `Song` データクラス (楽曲名 / shelf / book / version / time / composer / feat / 難易度別 level・notes 辞書) と `SongRepository` ([assets/data/all_songs.json](../assets/data/all_songs.json) ロード、部分一致検索、楽曲名→画像パス解決)
      - テスト: [tests/services/test_song_repository.py](../tests/services/test_song_repository.py) (実 JSON を用いたロード・部分一致・画像パス解決)
    - [x] **2.2: PlayRecord と Task のモデル**
      - [src/services/session.py](../src/services/session.py) に `PlayRecord` (song_name / difficulty / charming / combo)
      - [src/services/task.py](../src/services/task.py) に `Task` (type / set_value / value / current / cleared)
      - いずれもロジックを最小限に留めたデータモデル
      - テスト: [tests/services/test_task.py](../tests/services/test_task.py) (進捗・クリア判定の振る舞い)。`PlayRecord` の検証は 2.5 のセッションテストに含める
    - [x] **2.3: TaskGenerator**
      - [src/services/task_generator.py](../src/services/task_generator.py): [assets/data/all_topics.json](../assets/data/all_topics.json) から N 個ランダム生成。type の重複可否、`set` / `value` のサンプリング規則を実装
      - テスト: [tests/services/test_task_generator.py](../tests/services/test_task_generator.py)
    - [x] **2.4: TaskEvaluator**
      - [src/services/task_evaluator.py](../src/services/task_evaluator.py): type ごとの評価関数を辞書で保持し、`evaluate(task, play_record, all_plays, song_repo)` で判定
      - 全 type に対応 (title_*, level, level_total, result_*_total, notes_*, composer_*, time_*, version, book, shelf, difficult, featuring)
      - テスト: [tests/services/test_task_evaluator.py](../tests/services/test_task_evaluator.py) (type ごとの代表ケース)
    - [x] **2.5: Session と SessionManager**
      - [src/services/session.py](../src/services/session.py) に `Session` (タスク / プレイ履歴 / 回答履歴 / 開始時刻 / チャンネル / 所有者など)
      - [src/services/session_manager.py](../src/services/session_manager.py): シングルトン (`_current: Session | None`)。`start()` / `end()` / `reset()` / `current()` を提供
      - **タイマー処理は Discord 依存があるためステップ 4 以降に回し、本ステップではセッションオブジェクトの登録・取得・解放のみ実装する**
      - テスト: [tests/services/test_session.py](../tests/services/test_session.py), [tests/services/test_session_manager.py](../tests/services/test_session_manager.py)

- [x] **ステップ 3: 画像処理**
  - 変更範囲が広いため以下に細分化する。各サブステップ完了時にチェックを更新する
  - 全楽曲ジャケットは 300x300 RGB の前提 ([assets/images/](../assets/images/) を実測で確認済み)
    - [x] **3.1: ImageProcessor 骨格と単一画像エフェクト**
      - [src/services/image_processor.py](../src/services/image_processor.py): `ImageProcessor` クラス ([`SongRepository`](../src/services/song_repository.py) を依存注入)
      - 内部メソッドを実装: `_load_image` / `_apply_rotation` (90/180/270 ランダム) / `_apply_grayscale` (RGB のまま L→RGB に戻す) / `_apply_mosaic` (resize→resize 方式)
      - 効果適用順序は [パネル画像合成](#パネル画像合成) 節に準拠
      - テスト: [tests/services/test_image_processor.py](../tests/services/test_image_processor.py) (各エフェクトの単独適用・出力サイズ・モード)
    - [x] **3.2: パネルグリッド合成**
      - 内部メソッド `_overlay_panels(image, panel_count, cleared_indices) -> Image` を実装
      - `cleared_indices` のセルは加工せず、それ以外のセルは不透明な矩形で覆い、中央に番号 (1-origin) を描画
      - フォントは Pillow のデフォルト (`ImageFont.load_default()`) を使用
      - テスト: cleared セル中央のピクセルが元画像と等しい、非 cleared セル中央のピクセルがパネル色と等しいこと
    - [x] **3.3: compose 統合**
      - `compose(song_name, panel_count, cleared_indices, rotation_angle, grayscale, mosaic_block) -> BytesIO` を公開メソッドとして実装
      - 入力バリデーション: `panel_count` は平方数、`mosaic_block` は正、`cleared_indices` は `[0, panel_count)` 範囲内、楽曲名は SongRepository に存在
      - 出力は PNG 形式の `BytesIO` (discord.py の `discord.File` に直接渡せる形)
      - テスト: 出力 PNG サイズが元画像と一致、cleared 指定枚数分のパネルだけが剥がれていること、エラーケース (不正引数)

- [x] **ステップ 4: Bot とログ通知基盤**
  - 変更範囲が広いため以下に細分化する。各サブステップ完了時にチェックを更新する。依存関係の上流から順に実施
    - [x] **4.1: DiscordNotifier の実装**
      - [src/services/discord_notifier.py](../src/services/discord_notifier.py): `DiscordNotifier` クラスを実装
        - コンストラクタで `discord.Client` と `DiscordConfig` を受け取り、`log_channel_id` / `result_channel_id` を保持
        - `notify_error(message: str, exc: BaseException | None = None) -> None` — ログチャンネルへエラー詳細を送信 (traceback 整形含む)
        - `notify_session_result(image: BytesIO, spoiler_song_name: str, correct_answerers, summary) -> None` — 結果チャンネルへ画像と集計を送信 (楽曲名は description にスポイラー記法で出す)
        - チャンネル ID 未設定 / チャンネル取得失敗時は warning ログのみ出して握りつぶさない ([src/core/logger.py](../src/core/logger.py) を経由)
      - テスト: [tests/services/test_discord_notifier.py](../tests/services/test_discord_notifier.py) (`discord.Client` を mock し、`get_channel`・`send` 呼び出しの引数を検証。ID 未設定時に send が呼ばれないことも確認)
    - [x] **4.2: Bot クラスと cog 自動ロード基盤**
      - [src/core/bot.py](../src/core/bot.py): `commands.Bot` を継承する `SDBsBot` クラス
        - `setup_hook` で `src/cogs/` を `pkgutil.iter_modules` で走査し全 cog を `load_extension` する
        - `command_sync_guilds` が設定されていれば各 Guild に即時同期、空ならグローバル同期
        - `on_app_command_error` を実装し、`DiscordNotifier.notify_error` でログチャンネルへ送信し、ユーザーには ephemeral でエラーメッセージを返す
        - `DiscordNotifier` インスタンスは Bot 属性 (`self.notifier`) として保持し各 cog から参照可能にする
      - テスト: [tests/core/test_bot.py](../tests/core/test_bot.py) (`setup_hook` の cog ロード処理を mock 経由で確認、`on_app_command_error` が notifier を呼ぶこと)
      - `src/cogs/__init__.py` を空ファイルで作成 (パッケージ化のみ。実 cog はステップ 5 で追加)
    - [x] **4.3: main.py を Bot 起動仕様に変更**
      - [src/main.py](../src/main.py): 環境変数 `DISCORD_TOKEN` をロードし、`SDBsBot(...).run(token)` する起動処理に書き換え
      - 既存の [tests/test_main.py](../tests/test_main.py) を新仕様に合わせて更新 (`Bot.run` を mock し、token 未設定時に意味のあるエラーで終了することを確認)
      - `pytest` 全件パスを確認

- [x] **ステップ 5: Cog 実装**
  - 変更範囲が広いため以下に細分化する。各サブステップ完了時にチェックを更新する。依存関係の上流から順に実施
    - [x] **5.1: cog 共通基盤**
      - [x] **5.1.1: SessionManager のタイマー拡張**
        - [src/services/session_manager.py](../src/services/session_manager.py) に `on_warning` / `on_timeout` の async コールバック登録機構を追加
        - `start()` 時に `asyncio.create_task` で「残り時間 = 警告分」後に `on_warning` を、「セッション制限時間」後に `on_timeout` を呼ぶタスクを 2 本起動
        - `end()` / `reset()` で両タスクを `cancel()` し、コールバック登録もクリア
        - 遅延値は呼び出し側 (cog) で [`DiscordConfig`](../src/core/config.py) の `session_timeout_minutes` / `warning_minutes_before_end` から算出して `start()` の引数で注入する (manager 自身は config に依存しない設計)
        - テスト更新: [tests/services/test_session_manager.py](../tests/services/test_session_manager.py) (短い秒数を注入してコールバック発火順序を検証、`end()` 後に発火しないことを確認)
      - [x] **5.1.2: cog 共通ヘルパー**
        - 楽曲名オートコンプリート関数 (`/play`・`/answer` 共通) を [src/cogs/_helpers.py](../src/cogs/_helpers.py) に配置し、`SongRepository` 経由で部分一致候補を返す
        - [src/core/bot.py](../src/core/bot.py) の cog ローダーがアンダースコア始まりモジュール (`_helpers.py` 等) を `load_extension` 対象から除外するよう調整
        - cog テスト用の `discord.Interaction` mock ヘルパーを [tests/cogs/conftest.py](../tests/cogs/conftest.py) に追加 (`response.send_message` / `followup.send` / `user` / `channel` / `guild` の最低限の振る舞い)
    - [x] **5.2: `/start`** ([src/cogs/start_session.py](../src/cogs/start_session.py))
      - 引数: `panels` (`SessionConfig.allowed_panel_counts` から選択 / 既定 `default_panel_count`), `rotate` (既定 False), `grayscale` (既定 False), `mosaic` (`mosaic_levels` のラベル選択 / 既定「なし」)
      - 楽曲をランダム選択 → `TaskGenerator` で N 個のタスクを生成 → `SessionManager.start(...)` でセッション登録 → `ImageProcessor.compose` で初期画像 (全パネル未開放) を合成
      - 投稿メッセージをピン留めし、メッセージ ID を `Session` に保持する
      - SessionManager の `on_warning` に「残り 10 分」のチャンネル通知を、`on_timeout` に `/end` と同等処理 (結果通知 + ピン解除) を登録
      - テスト: [tests/cogs/test_start_session.py](../tests/cogs/test_start_session.py) (既セッション存在時の拒否、引数バリデーション、ピン留め呼び出し、コールバック登録)
    - [x] **5.3: `/end`** ([src/cogs/end_session.py](../src/cogs/end_session.py))
      - 現セッションが無い場合は ephemeral でエラー応答
      - 結果チャンネルへ embed を投稿 (詳細は [結果通知](#結果通知) を参照)
      - 元のピン留めメッセージのピンを解除
      - `SessionManager.end()` を呼んでセッションを破棄 (タイマーも停止)
      - 終了後処理は [`SessionFinalizer`](../src/services/session_finalizer.py) に委譲して自動タイムアウトと共通化する
      - テスト: [tests/cogs/test_end_session.py](../tests/cogs/test_end_session.py) (embed 内容、ピン解除、SessionManager 呼び出し、セッション無し時のエラー応答、正解者 0 人ケース)
    - [x] **5.4: `/reset`** ([src/cogs/reset_session.py](../src/cogs/reset_session.py))
      - `SessionManager.reset()` を呼び、ピン留めメッセージのピン解除のみ実行 (結果チャンネルへの投稿は行わない)
      - テスト: [tests/cogs/test_reset_session.py](../tests/cogs/test_reset_session.py)
    - [x] **5.5: `/progress`** ([src/cogs/show_progress.py](../src/cogs/show_progress.py))
      - 現セッションのタスク一覧 + 進捗を embed で表示。各 task は `current/set_value` 形式、cleared 済みは記号で視覚化
      - セッション無し時は ephemeral でエラー応答
      - テスト: [tests/cogs/test_show_progress.py](../tests/cogs/test_show_progress.py)
    - [x] **5.6: `/play`** ([src/cogs/input_play.py](../src/cogs/input_play.py))
      - 引数: `song` (autocomplete), `difficulty`, `charming`, `combo` (`is_natural_number` でバリデーション)
      - `PlayRecord` を生成しセッションに追加 → 全タスクを `TaskEvaluator` で評価 → 進捗のあったタスクを embed で返答
      - パネルが新たに剥がれていれば `ImageProcessor.compose` で画像を再合成し、ピン留めメッセージを編集 (添付画像差し替え)
      - テスト: [tests/cogs/test_input_play.py](../tests/cogs/test_input_play.py)
    - [x] **5.7: `/answer`** ([src/cogs/answer_song.py](../src/cogs/answer_song.py))
      - 引数: `song` (autocomplete、5.1.2 のヘルパー利用)
      - 正解判定後、ephemeral で `🎉 正解です！` / `❌ 不正解です` (success / error embed) を返す。正解時のみ `Session.correct_answerers` に `(user_id, user_name)` を追加 (既存なら冪等)
      - 公開チャンネルへの出力は無し。セッション終了は引き起こさない
      - テスト: [tests/cogs/test_answer_song.py](../tests/cogs/test_answer_song.py) (正解 / 不正解 / 同一ユーザー重複登録の冪等性)
  - 各 cog 追加時にエンドツーエンドの想定動作を README/DEVELOPMENT.md に追記

- [x] **ステップ 6: Docker 化**
  - `Dockerfile` と `docker-compose.yml`
  - `docker compose up --build` で 24h 稼働確認

- [x] **ステップ 7: 表示・運用品質の強化 (Phase 5 後)**
  - 実装後のフィードバックを受けて、表示一貫性 / 進行透明性 / 設定運用性を高めるための機能強化。各サブステップは独立にリリース可能
    - [x] **7.1: Bot メッセージの embed 統一**
      - 全 cog の応答を embed 化し、用途別カラー (info / success / warning / error) のビルダを [src/cogs/_helpers.py](../src/cogs/_helpers.py) に集約
      - `DiscordNotifier.notify_error` も embed 化
    - [x] **7.2: お題への `play_quality` 導入**
      - `Task` に `play_quality: Literal["AC", "FC", "プレイ"]` を追加し、`description_template` の placeholder を `value` / `set` / `play` の 3 つに整理
      - [`TaskGenerator`](../src/services/task_generator.py) で AC=1 / FC=3 / プレイ=6 の重み付き抽選
      - [`TaskEvaluator._satisfies_quality`](../src/services/task_evaluator.py) で品質フィルタを集中化 (累積系も `all_plays` を再フィルタしてから集計)
    - [x] **7.3: `/play` の上限超過拒否**
      - 楽曲メタにない難易度、`charming` / `combo` がノーツ数を超える入力を ephemeral の warning embed で拒否し、副作用なしで戻す
    - [x] **7.4: 進捗 / 結果表示の刷新**
      - `/start` / `/play` / `/progress` の embed を絵文字 + fields 形式に統一 (`build_topic_field` で 1 タスク 1 field)
      - `/end` 完了応答に green の success embed を採用
      - `level_total` 集計時、文字列レベル (例: `"L"` / 2 進数表記) の Ex 譜面プレイをスキップ
    - [x] **7.5: 制限時間終了通知**
      - タイムアウト時にセッションチャンネルへ「制限時間が終了しました」warning embed を投稿してから `SessionFinalizer.finalize` を呼ぶ
    - [x] **7.6: 結果通知の楽曲名スポイラー化**
      - 結果 embed の楽曲名を従来のマスク (`*****`) から Discord スポイラー記法 (`||...||`) に変更
      - `SessionFinalizer.format_spoiler_song_name` で内側を `_SPOILER_MIN_WIDTH=20` 文字までパディングし、短い楽曲名で文字数が見抜かれないようにする
    - [x] **7.7: 回転角度の固定 (セッション中)**
      - [`ImageProcessor.pick_rotation_angle`](../src/services/image_processor.py) で角度を 1 度だけ決定し、`Session.rotation_angle` に保存
      - `compose` の引数は `rotate: bool` から `rotation_angle: Optional[int]` に変更し、`/start` / `/play` / `SessionFinalizer` から同じ値を渡す
      - `_ROTATE_CHOICES` に `0` を追加し「回転オプション有効でも見た目が変わらない」抽選も許容
    - [x] **7.8: `/play` ピン留め画像の差し替え修正**
      - `attachments` を新 `discord.File` で上書きする際、embed の `image.url` を `attachment://panels.png` で再バインドし、新画像が embed 内に表示されるようにする (従来は別添付として末尾に並ぶ事象が発生していた)


## 動作検証

### 単体テスト

- `pytest` (既存設定: [pytest.ini](../pytest.ini) で `--cov=src`)
- 追加対象: `tests/services/test_*.py`, `tests/cogs/test_*.py` (cog は [tests/cogs/conftest.py](../tests/cogs/conftest.py) の Interaction mock を使用)
- 既存テスト ([tests/test_main.py](../tests/test_main.py), [tests/core/](../tests/core/), [tests/utils/](../tests/utils/)) は main.py 変更に追従して更新

### 結合テスト (手動)

1. テストサーバーで `.env` に `DISCORD_TOKEN` / `LOG_CHANNEL_ID` / `RESULT_CHANNEL_ID` を設定し `python src/main.py` 起動
2. `/start panels:4 mosaic:中 rotate:True` → ピン留め確認、パネル 4 枚 + モザイク中の画像表示確認 (回転角度がセッション中固定であることを次手順で確認)
3. `/play song:Aya difficulty:Hard charming:300 combo:300` → 該当タスクが進捗 +1 されパネルが剥がれること、ピン留め画像が同じ角度のまま差し替わることを確認 (別添付として末尾に並ばないこと)
4. `/play` で `charming` または `combo` を譜面ノーツ数より大きい値で送信 → warning embed で ephemeral 拒否され、`/progress` で進捗が変動していないことを確認
5. `/progress` → タスク状態の表示確認。`play_quality` ラベル (AC / FC / プレイ) が description に出ること
6. `/answer song:Aya` → 本人にのみ ephemeral で 🎉/❌ 応答が返ることを確認。正解後も `/play` ・ `/answer` を続けられること、複数メンバーが並行して回答できることを確認
7. `/end` → 結果チャンネルへ embed (スポイラー楽曲名・最終パネル画像・正解者一覧) を投稿し、ピン解除されることを確認
8. 30 分タイマー (`session_timeout_minutes` を一時的に 1 にして検証) → 警告 → 「制限時間が終了しました」通知 → 自動結果投稿
9. エラーを意図的に発生 (例: 楽曲データを退避して `/start`) → ログチャンネル投稿確認

### Docker 検証

```bash
docker compose up --build -d
docker compose logs -f
```

コンテナが落ちた際 `restart: always` で復帰することを確認。
