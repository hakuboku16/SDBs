# DEEMO×アタック25 Discord bot 設計

作成日: 2026-06-04 / 状態: 承認済み

## Context(なぜ作るか)

リズムゲーム DEEMO の知識を使い、クイズ番組「アタック25」風の盤面で遊ぶ Discord bot。

- DEEMO に関する「お題」を複数生成し、お題の数だけ盤面パネルを作る
- パネルの背後に 1 枚の楽曲画像(隠し曲)を隠す
- プレイヤーが楽曲のプレイ結果を申告するとお題が進行し、達成されたお題のパネルがめくれて画像が部分開示される
- 部分開示された画像から隠し曲名を当てる

現状はテンプレート([src/core/config.py](src/core/config.py) / [src/core/logger.py](src/core/logger.py) / Docker / uv / pytest)のみで、Discord 層・ゲーム層は未実装。本設計はその全体を、テンプレートの設計様式(pydantic-settings の環境別 Settings、ハンドラ追加式ロガー、pytest)を踏襲して構築する。

## 確定した方針

| 項目 | 決定 |
|:--|:--|
| Discord ライブラリ | discord.py(app_commands + ext.commands.Cog) |
| セッション状態 | インメモリ(単一プロセス内、再起動で揮発)|
| 盤面表示 | Pillow で画像合成(楽曲画像をタイル分割し未達成タイルを番号パネルで被覆)|
| 進行方法 | プレイ自己申告制。/report で 楽曲名・難易度・combo・charming を申告し、全お題と照合 |
| パネル数 | セッション開始時に **4 / 9 / 16 / 25** から選択(=2×2/3×3/4×4/5×5、既定 9)|
| 画像加工 | /session_start で 回転(0/90/180/270ランダム)・グレースケール・モザイク(300/150/90/45/27px)を任意指定(既定すべて「しない」)|
| 正解者 | セッション中に記録し、終了時アーカイブで発表 |

## アーキテクチャ概要

ゲームロジックを `game/` に集約し Discord 非依存で単体テスト可能にする。`cogs/` の各コマンドは入出力の薄いアダプタに留める(責務分離)。

```
src/
  main.py                 # 改修: bot 起動(設定読込→ロガー→Bot.run)
  core/
    config.py             # 拡張: Discord/ゲーム設定を追加(既存 Settings 様式を踏襲)
    logger.py             # 拡張: WARNING+ をログチャンネルへ送る Handler を追加
  bot/
    client.py             # discord.py Bot サブクラス。cogs ロード、on_ready で command sync
    discord_log_handler.py# logging.Handler。WARNING+ を非同期キュー経由でログchへ送信
  game/
    models.py             # Song / Topic / PlayReport / GameSession 等の dataclass
    song_repository.py    # all_songs.json 読込、部分一致検索、画像解決、派生属性・一覧導出
    topic_catalog.py      # all_topics.json(テンプレート)読込
    topic_types.py        # 型ごとの「生成器・述語・進捗種別・説明整形」レジストリ
    topic_generator.py    # 実在曲で必ず達成可能なお題を N 個生成
    play_matcher.py       # PlayReport を全お題に照合し進捗加算・新規達成を検出
    session_manager.py    # 単一アクティブセッションのライフサイクル・タイマー・盤面状態
    board.py              # Pillow 盤面合成(画像加工・分割・番号パネル被覆・開示)
  cogs/                   # 1 スラッシュコマンド 1 ファイル
    session_start.py      # /session_start (panels, rotate, grayscale, mosaic)
    session_end.py        # /session_end
    session_progress.py   # /progress (ephemeral)
    session_clear.py      # /session_clear
    song_report.py        # /report (song, difficulty, combo, charming)
    answer.py             # /answer (song)  ephemeral
```

追加依存: `discord.py`、`Pillow`(`uv add`)。

コマンド識別子は ASCII(例 `/session_start`)+ 日本語 description/ローカライズで定義する(Discord の互換性確保のため)。

## データモデル(models.py)

- **Song**: `title, shelf, book, version, level{Easy,Normal,Hard}, notes{...}, time, composers[list], featuring[list|None], image_path`
  - `feat.` キーを持つ曲は featuring。`COMPOSER` が複数要素なら複数作曲者。
- **PlayReport**: `song, difficulty, combo, charming`(申告 1 件)
- **Topic**: `panel_no, type, play_condition(プレイ/FC/AC), filter_value, required(set値), progress_kind(COUNT|SUM), progress, completed, description`
- **GameSession**: `panel_count, grid_size, hidden_song, image_options(rotate角|grayscale|mosaic_px), topics[], revealed_panels(set), correct_answerers(set[user_id]), started_at, ends_at`
  - 実装注記(M3以降): `game/` を Discord 非依存に保つため、`board_message_ref`/`topic_message_ref`/`timer_task` は GameSession に持たせず、bot 層の `GameService`(`src/bot/game_service.py`)が保持する。

## お題エンジン(本ゲームの核)

### 生成(topic_generator + topic_types)
1. テンプレートを選ぶ(できるだけ型を重複させない。N > 型数なら重複許可)
2. `set`=[min,max,step] から閾値/必要回数を抽選(例 [2,4,1]→{2,3,4})
3. `value` を解決: `null` / `{range:[min,max,step]}` / `{candidate, choice}`(文字列→文字、リスト、`version_list`/`book_list`/`shelf_list` は楽曲データから導出)
4. プレイ種別を抽選: プレイ60% / FC30% / AC10%(**COUNT 型・SUM 型とも抽選する**)
5. **達成可能性検証**: 解決した条件に実在曲が 1 件以上一致するまで再抽選(パネルが永久に開かない事故を防ぐ)
6. description テンプレートの `value`/`set`/`play` を整形(型ごとに value の描画が異なるためレジストリで担当)

### 判定(play_matcher + topic_types)
PlayReport 1 件を全お題に照合。各お題の進捗は 2 種:
- **COUNT 型**: 「楽曲フィルタ一致」かつ「プレイ種別条件」を満たすプレイで +1
  - プレイ: 常に成立 / FC: `combo == NOTES[難易度]` / AC: `combo == NOTES[難易度] かつ charming == NOTES[難易度]`
- **SUM 型**(level_total / result_combo_total / result_charming_total): 「楽曲フィルタ一致」かつ「プレイ種別条件(プレイ=常時 / FC / AC)」を満たすプレイの申告値(難易度のLEVEL / combo / charming)**のみ**を累積し、閾値到達で達成

楽曲フィルタは型ごとの述語(レジストリ)で表現:
- title 系(include/startswith/endswith/len_below/len_above/blank): 曲名の文字列演算
- difficult: 申告難易度 == value / level: 曲が Lv.value の譜面を保有
- notes_below/above・notes_density_below/above・notes_endswith: 曲のいずれかの譜面が条件を満たす(密度 = NOTES/TIME)
- composer_name_startswith/endswith: COMPOSER のいずれかが該当文字で開始/終了
- composer_members: `len(COMPOSER) > 1` / featuring: `feat.` フィールドを保有
- time_below/above: TIME 比較 / version: VERSION 一致 / book: 収録ブック一致 / shelf: 収録棚一致

新規達成お題が出たら、その `panel_no` を `revealed_panels` に追加し盤面を再合成する。

## ゲームフロー(コマンド別)

- **/session_start(panels, rotate, grayscale, mosaic)**: 既存セッションがあれば拒否 → 画像を持つ曲から隠し曲を抽選 → 画像加工設定を確定(後述)→ お題を N 個生成 → 盤面(全タイル番号パネル被覆)を投稿、お題リストを投稿してピン留め → 30 分タイマー開始(20 分経過=残り10分で予告、30 分で自動終了)
  - **panels**: 4 / 9 / 16 / 25(既定 9)
  - **rotate**: する/しない(既定しない)。する場合、開始時の画像生成時に 0/90/180/270° からランダムで 1 つ選びセッション中固定
  - **grayscale**: する/しない(既定しない)
  - **mosaic**: しない(300px) / 弱(150px) / 中(90px) / 強(45px) / 最強(27px)(既定しない)。指定 px へ縮小→300px へ拡大してモザイク化
- **/report(song,difficulty,combo,charming)**: セッション無ければ拒否 → 部分一致で曲解決(0件=エラー / 複数=候補提示し絞り込み依頼) → 全お題照合 → 達成パネルを開示し盤面メッセージとピン留めお題リストを更新 → **該当したお題があれば「どのお題に該当したか」を embed で公開表示**(ephemeral ではなく公開)
- **/answer(song)**: ephemeral。部分一致で隠し曲と照合 → 正解なら「正解」+ user_id を記録 / 不正解なら「不正解」。正解後もゲームは継続(公開ネタバレなし)
- **/progress**: ephemeral。現在の盤面・お題進捗・残り時間を表示
- **/session_end**(コマンド or タイマー): **その時点の盤面画像(全開示はしない)** をアーカイブchへ「現時点の画像 + ネタバレ表示の曲名(`||曲名||`) + 正解者一覧」として投稿 → ピン留め解除・状態破棄
- **/session_clear**: アクティブセッションをアーカイブ無しで強制破棄(復旧用)。終了との違いはアーカイブを残さない点

## 盤面描画(board.py)

- 入力: 隠し曲画像、グリッド辺(2/3/4/5)、開示済みタイル集合、画像加工設定(rotate角・grayscale・mosaic px)
- 基準キャンバスは 300px 正方。隠し画像へ加工を適用(回転→グレースケール→モザイクの順。モザイクは指定 px へ縮小後 300px へ拡大)した上で grid×grid に分割。未開示タイルは不透明パネル+中央に番号、開示タイルは加工後の画像スライスを表示し合成、PNG バイト列を返す
- 加工はセッション開始時に確定し以後固定(回転角もこのとき抽選)。開示済みタイルも加工後の画像で表示される
- パネル番号 1..N が `panel_no`(=お題)に一致。ピン留めお題リストは「パネルN: 説明 [進捗 x/y]」を表示
- 開示のたび再合成して盤面メッセージを `message.edit` で差し替え

## Discord ロギング

`logging.Handler` を追加し、WARNING+ レコードを **asyncio キュー経由**(`call_soon_threadsafe`)でバックグラウンドタスクがログchへ投稿する。`discord.*` ロガー由来のレコードは転送除外しループを防ぐ。既存 `setup_logger` のハンドラ追加様式に合わせる。

## 設定 / 環境変数(config.py 拡張・.env.example 更新)

`BaseAppSettings` に追加(型ヒント必須):
`discord_token`(秘匿), `game_guild_id`, `log_guild_id`, `log_channel_id`, `archive_channel_id`, `songs_data_path`/`topics_data_path`/`images_dir`(既定 assets/...), `session_duration_minutes=30`, `session_warning_minutes=10`。
秘匿値・ID は `.env` 管理(`.env.example` に追記)。

## エラーハンドリング

- コマンドガード(未/重複セッション、無効入力)は ephemeral で通知
- 部分一致 0 件/複数件はそれぞれ案内
- アプリコマンド共通エラーハンドラで例外を捕捉 → ERROR ログ(=ログchへ)+ 利用者へ汎用 ephemeral 応答
- アセット欠落は WARNING ログで縮退

## テスト戦略(TDD、ゲームロジック中心)

Discord 非依存の `game/` を単体テスト:
- song_repository: 部分一致、画像解決(`’` 等の Unicode 差異に備え正規化)、棚/ブック/version 一覧導出
- topic_generator: 件数・達成可能性・値域・プレイ種別分布
- topic_types: 型ごとの述語をテーブル駆動で検証(既知曲で真偽)
- play_matcher: 申告が正しいお題のみ進め、閾値で達成、SUM はプレイ種別条件を満たす申告のみ累積
- session_manager: 重複開始拒否・終了アーカイブ・clear 復帰(時刻は注入可能に)
- board: 出力が想定サイズ(300px)の PNG で、被覆/開示タイルが区別され、加工(回転/グレースケール/モザイク)が反映される
- config: 新設定の既定値テストを既存様式で追加

cogs は薄いため手動結合テスト(テストサーバ)で確認。

## 実装マイルストーン(段階導入)

1. **M1 基盤**: config/.env 拡張、bot/client・cog ローダ・command sync、Discord ログハンドラ。検証: bot 接続・コマンド表示・WARNING がログchに届く
2. **M2 お題生成**: song_repository / topic_catalog / topic_types / topic_generator(+テスト)。検証: 実データから達成可能なお題を N 個生成
3. **M3 セッション+照合**: session_manager(タイマー)/ play_matcher(+テスト)。検証: 開始→申告→進捗を Discord 抜きで確認
4. **M4 盤面**: board(Pillow、画像加工含む)+ セッションへの組込み(盤面投稿・ピン・達成時開示)。検証: 加工・合成・開示
5. **M5 結線**: 6 cogs を端から端まで配線、アーカイブ・アナウンス・/report の該当お題 embed。検証: テストサーバで一連プレイ

## 検証(エンドツーエンド)

- ローカル: `APP_ENV=test uv run pytest`(ロジック)
- テストギルド実機: `/session_start panels:4` で 2×2 盤面+ピン留めお題 → 一致曲を必要回数 `/report` でパネル開示・該当お題 embed 公開 → `/answer` 正解で ephemeral「正解」+記録 → `/progress` 確認 → `/session_end` でその時点の画像をアーカイブ(ネタバレ曲名+正解者)・ピン解除 → `/session_clear` で強制リセット → ログchに WARNING 着弾

## 確認したい前提(実装中に検証)

- コマンド識別子は ASCII + 日本語ローカライズで定義(Discord 互換性のため)。日本語識別子希望なら変更可
- 画像ファイル名と曲名は Unicode 正規化込みで突合(`’` など)
