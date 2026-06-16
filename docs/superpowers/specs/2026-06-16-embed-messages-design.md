# 送信メッセージの Embed 化 設計

## 目的

bot がユーザーへ送るメッセージを Discord の Embed 形式へ統一し、見た目の一貫性と状態の視認性(色分け)を高める。ログチャンネルへのコードブロック転送のみ現状維持とする。

## スコープ

- 対象: 公開メッセージ + ephemeral メッセージ(確認・エラー・各種応答)
- 対象外: ログチャンネルへのコードブロック転送(`src/bot/client.py` `_consume_log_queue`)

## 色の方針(意味ごとの色分け)

| 用途 | 名前 | 色 |
|---|---|---|
| 成功・確認 | SUCCESS | `0x57F287`(緑) |
| エラー・不正解 | ERROR | `0xED4245`(赤) |
| 予告・ガード | WARNING | `0xE67E22`(オレンジ) |
| 情報(盤面・進捗) | INFO | `0x3498DB`(青) |
| アーカイブ | NEUTRAL | `0x95A5A6`(灰) |

## コンポーネント

### 新規: `src/bot/embeds.py`

意味ごとの色定数と汎用ビルダ関数を提供する。各 cog / `game_service` はこれを呼ぶだけにする。

```python
class EmbedColor(IntEnum):
    SUCCESS = 0x57F287
    ERROR   = 0xED4245
    WARNING = 0xE67E22
    INFO    = 0x3498DB
    NEUTRAL = 0x95A5A6

def success(description=None, *, title=None) -> discord.Embed
def error(description=None, *, title=None)   -> discord.Embed
def warning(description=None, *, title=None)  -> discord.Embed
def info(description=None, *, title=None)     -> discord.Embed
def neutral(description=None, *, title=None)  -> discord.Embed
```

- 各関数は `discord.Embed(title=title, description=description, color=...)` を返すだけの薄いラッパ。
- 画像付き Embed は呼び出し側で `embed.set_image(url="attachment://board.png")` を付け、`discord.File` と一緒に送る。
- 既存の `format_*`(`format_topic_list` 等)は文字列を返したまま据え置き(既存テスト維持)、Embed の description に渡す。

### 盤面とお題の統合(`src/bot/game_service.py`)

現状は盤面メッセージとお題メッセージの2つ(それぞれピン留め・個別編集)。これを **1つのメッセージ**へ統合する。

- 状態スロット `board_message` / `topic_message` を単一の `session_message: discord.Message | None` へ置き換える。
- `post_session_messages`: INFO 色 Embed(title「盤面とお題」、description=`format_topic_list`、`set_image` で盤面画像)を1通送ってピン留めし、`session_message` に保持。
- `refresh_board`: 同じ Embed を組み直し、`session_message.edit(embed=..., attachments=[file])` で盤面画像とお題リストを同時更新。
- `_unpin_messages`: 単一メッセージのピン解除と参照クリアに変更。
- `run_timer`: 予告送信先チャンネル参照を `board_message.channel` → `session_message.channel` に変更。

## メッセージごとの割り当て

### 公開メッセージ

| 箇所 | Embed | 色 |
|---|---|---|
| 盤面+お題(統合、ピン留め) | title「盤面とお題」+ `format_topic_list` + 画像 | 青 |
| 盤面+お題の更新(`refresh_board`) | 上記を `edit` | 青 |
| 終了アーカイブ | title「セッション終了」+ `format_archive_caption` + 画像 | 灰 |
| 終了予告 | title「終了予告」+「残りN分です。」 | オレンジ |
| お題達成(既存 Embed) | 既存に色を追加 | 緑 |

### ephemeral メッセージ

| 文言 | 色 |
|---|---|
| 「セッションを開始しました」「セッションを終了しました」「セッションを破棄しました」「正解」「申告を反映しました」 | 緑 |
| 「不正解」「進行中のセッションがありません」「このチャンネルには投稿できません」「アーカイブ用チャンネルを取得できませんでした…」「コマンドの実行中にエラーが発生しました…」「『曲名』に一致する曲が見つかりません」 | 赤 |
| 「既にセッションが進行中です」「候補が複数あります…」 | オレンジ |
| 進捗表示(`progress`、画像付き) | 青 |
| 「申告を反映しました。達成したお題はありません」 | 青 |

## エラーハンドリング

- 既存の応答済み/未応答分岐(`_on_app_command_error`)はそのまま。content を embed に置き換えるだけ。
- 画像付き Embed の編集時は `attachments=[file]` を毎回渡し、`attachment://board.png` 参照を維持する。

## テスト方針

- `embeds.py` の各ビルダに対し、color と title/description が期待どおり設定されることを検証するユニットテストを追加。
- 既存の `format_*` テストは無変更で通ること(回帰確認)。
- `game_service` の統合点(`session_message` への一本化)は既存テストが参照していないため破壊しないが、Discord 送信は外部依存のため自動テスト対象外。手動確認で補う。
