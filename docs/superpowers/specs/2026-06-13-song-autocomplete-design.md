# 楽曲名オートコンプリート設計

> 親設計書 [2026-06-04-deemo-attack25-bot-design.md](2026-06-04-deemo-attack25-bot-design.md) への追補。
> `/report`・`/answer` の `song` 引数に Discord のオートコンプリート(入力中の候補表示)を追加する。

## 背景・目的

現状 `song` 引数は素のテキスト入力で、入力中に候補が出ない。曲名を正確に覚えていないと部分一致解決(送信後)に頼るしかなく、操作性が悪い。Discord のオートコンプリートで入力中に曲名候補を提示し、選択即確定できるようにする。

## スコープ

- 対象コマンド: `/report` と `/answer` の両方(`song` 引数を持つ 2 コマンド)。
- `/answer`(隠し曲当て)も全曲名を候補に出す。候補は全曲なので正解は漏れない。
- 空入力(未入力)時も先頭 25 件を提示する。

## 設計

### 1. 候補抽出(Discord 非依存・TDD 対象)

`GameService` にメソッドを追加する。

```
def suggest_song_titles(self, query: str, *, limit: int = 25) -> list[str]
```

- 空/空白の `query`: 全曲名を曲名昇順でソートし先頭 `limit` 件。
- 非空の `query`: 既存 `SongRepository.search(query)`(NFC 正規化 + 大文字小文字無視の部分一致)の結果を曲名昇順でソートし `limit` 件に切り詰め。
- 返却は曲名(`str`)のリスト。Discord 制約(候補 25 件・name 100 文字)に収まる前提(DEEMO 曲名は十分短い)。
- セッション非依存(曲リストはセッションに依存しない)。

### 2. 完全一致優先の解決(Discord 非依存・TDD 対象)

オートコンプリートで選んだ曲名が別曲名の部分文字列だと(例: 「Dream」と「Dreamy」)、`resolve_song` が複数一致して「候補が複数」になる。これを防ぐため `resolve_song` を次のとおり小改修する。

- `query` が正規化後にいずれかの曲名と**完全一致**するなら、その曲を一意に返す(部分一致で複数ヒットしても完全一致を優先)。
- 完全一致が無い場合は現状どおり: 0 件 → `SongNotFound`、複数 → `AmbiguousSong`、1 件 → その曲。

これによりオートコンプリート選択後の送信が確実に通る。

### 3. cog 配線(薄いアダプタ・import スモークのみ)

`song_report.py` / `answer.py` に `song` 用のオートコンプリートコールバックを追加し、`@app_commands.autocomplete(song=...)` で配線する。

```python
async def _song_autocomplete(
    self, interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    return [
        app_commands.Choice(name=title, value=title)
        for title in self.bot.game.suggest_song_titles(current)
    ]
```

セッション有無に関わらず候補を返す(曲リストはセッション非依存のため、`game.session is None` でも提示する)。`name`・`value` ともに曲名。

## テスト

- `suggest_song_titles`(TDD): 空入力→曲名昇順で先頭 N 件、部分一致での絞り込み、25 件上限の切り詰め。
- `resolve_song` 完全一致優先(TDD): 「Dream」「Dreamy」が両在する中で `resolve_song("Dream")` が「Dream」を一意に返す。既存の 0件/複数/1件の挙動は維持。
- cog: import スモーク(コールバックは薄い)。

## 非対象(YAGNI)

- 候補の曲名以外のメタ情報(難易度・shelf 等)表示。
- ファジーマッチ(タイポ許容)。既存の部分一致のみ。
- 25 件超のページング。
