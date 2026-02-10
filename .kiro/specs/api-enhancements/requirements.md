# ユーザーストーリー: APIレスポンス拡充とエラーハンドリング改善

## 概要

YouTube Summary APIのレスポンスに、投稿日・動画の長さ・再生回数などのメタデータを追加し、エラー発生時の原因特定を容易にする。

## 背景

### 現状のAPI

- iPhoneショートカットからYouTube動画のURLを送信し、字幕データを取得して活用している
- Docker Compose + Tailscaleネットワーク上で常時稼働中（2週間以上安定運用実績あり）
- 現在返しているデータは `title`, `channel_name`, `transcript` の3項目のみ
- メタデータ取得には YouTube oEmbed API を使用（取得できる項目が限定的）
- 字幕取得には `youtube-transcript-api` 1.1.0 を使用

### 現状の課題

1. **投稿日が取れない** — いつ公開された動画かわからない
2. **動画の長さが取れない** — 見る価値の事前判断ができない
3. **取得項目が少なすぎる** — 再生回数・タグ・カテゴリ等がない
4. **失敗理由が不明確** — 字幕がないのか、動画が存在しないのか、レート制限なのか区別しづらい
5. **依存ライブラリの問題** — `pytube` 15.0.0 が依存に含まれるが、2023年5月以降メンテナンス停滞中で実質動作しない

## 最重要方針: 後方互換性

**既存のiPhoneショートカットが一切の変更なしで、現在とまったく同じデータを受け取れること。**

- 既存の5フィールド（`success`, `message`, `title`, `channel_name`, `transcript`）は名前・型・内容ともに変更なし
- `transcript` のフォーマット（タイムスタンプ付きテキスト）も現在と同一
- 新規フィールドが追加されるのみ（既存フィールドの削除・変更は一切行わない）
- `status`（文字列 `"ok"` / `"error"`）を新設し、iPhoneの言語設定によるbool値ローカライズ問題（日本語環境で `true` が「はい」になる等）を回避。ショートカット側では `status` の文字列比較で分岐することを推奨

## ユーザーストーリー

### US-1: 動画のメタデータを取得したい

**As a** iPhoneショートカットのユーザー
**I want** APIレスポンスに投稿日・動画の長さ・再生回数などのメタデータが含まれている
**So that** 字幕だけでなく、動画の基本情報を一度のAPIリクエストで把握できる

### US-2: 失敗理由を正確に知りたい

**As a** iPhoneショートカットのユーザー
**I want** APIリクエストが失敗した際に、プログラムで判別可能なエラーコードが返される
**So that** 「字幕がない」「動画が存在しない」「レート制限」等を区別して、ショートカット側で適切な対応ができる

### US-3: 失敗時でも取得できた情報は受け取りたい

**As a** iPhoneショートカットのユーザー
**I want** 字幕取得に失敗しても、取得できたメタデータ（タイトル・投稿日等）はレスポンスに含まれている
**So that** 「字幕は取れなかったがどんな動画だったか」は把握できる

### US-4: iPhoneの言語設定に依存しない成功/失敗判定をしたい

**As a** iPhoneショートカットのユーザー
**I want** bool値の `success` とは別に、文字列で成功/失敗を返す `status` フィールドがある
**So that** iPhoneの言語設定が日本語でも英語でも、ショートカットの条件分岐が同じロジックで動作する

#### 背景

iPhoneショートカットでは、JSONのbool値（`true`/`false`）が端末の言語設定に応じてローカライズされる（日本語環境では「はい」「いいえ」になる）。これにより、bool値での条件分岐は言語設定によって動作が変わってしまう。文字列 `"ok"` / `"error"` であればローカライズの影響を受けない。

## 技術方針

### ライブラリ構成の変更

| 変更 | 旧 | 新 |
|------|----|----|
| メタデータ取得 | oEmbed API のみ | **yt-dlp（主軸）、oEmbed API（フォールバック）** |
| 文字起こし | youtube-transcript-api 1.1.0 | youtube-transcript-api **v1.2.x系**（破壊的API変更あり） |
| 削除 | pytube 15.0.0 | **依存から削除** |

### 取得の優先順位（1つで済むならそれが最善）

1. **yt-dlp でメタデータを一括取得**（title, channel_name 含む全項目）
2. yt-dlp が失敗した場合のみ **oEmbed API にフォールバック**（title, channel_name, thumbnail_url の最低限）
3. **youtube-transcript-api で字幕を取得**（メタデータ取得とは独立して実行）

yt-dlpで `title` と `channel_name` も取得できるため、正常時はoEmbed APIの呼び出しは不要。oEmbedはyt-dlp失敗時の保険として残す。

### yt-dlp 選定理由

- 2026年2月4日にもリリースあり。開発が非常に活発で、YouTubeの仕様変更への追従が最速
- `extract_info(url, download=False)` でダウンロードせずメタデータのみ取得可能
- title, channel_name を含む全メタデータが1回の呼び出しで取得可能
- 認証不要、APIキー不要、クォータ制限なし
- 専門家3名の意見が全員一致で推奨

### yt-dlp のシステム要件

- **yt-dlp 2025.11.12以降、YouTubeの完全サポートにJavaScriptランタイム（Deno推奨）が必須**
- `pip install yt-dlp[default]`（yt-dlp-ejsパッケージを含む）でインストール
- Docker環境ではDenoのインストールが必要

### youtube-transcript-api の破壊的変更（v1.1.0 → v1.2.x）

最新バージョンは v1.2.3（2025年10月13日リリース）。v1.2.0で旧APIが完全削除されている:

| 旧API（v1.1.0、現在使用中） | 新API（v1.2.x） |
|--------------------------|----------------|
| `YouTubeTranscriptApi.get_transcript(video_id, languages=[...])` | `YouTubeTranscriptApi().fetch(video_id, languages=[...])` |
| `YouTubeTranscriptApi.list_transcripts(video_id)` | `YouTubeTranscriptApi().list(video_id)` |
| クラスメソッド | **インスタンスメソッド** |
| 戻り値: `list[dict]` | 戻り値: `FetchedTranscript`（`.to_raw_data()` で旧形式に変換可能） |

**`fetch()` ショートカットで `transcript_language` と `is_generated` も取得可能:**

```python
api = YouTubeTranscriptApi()
fetched = api.fetch(video_id, languages=['ja', 'en'])
fetched.language_code   # → 'ja'（transcript_language に対応）
fetched.is_generated    # → False（is_generated に対応）
fetched.to_raw_data()   # → [{'text': '...', 'start': 0.0, 'duration': 1.5}, ...]
```

`list()` → `find_transcript()` → `fetch()` の3ステップは不要。`fetch()` 1回で本文・言語コード・自動生成フラグがすべて取得できる。

### youtube-transcript-api の例外クラス（v1.2.x）

v1.0.0以降で追加された例外クラスがある:

| 例外クラス | 説明 |
|-----------|------|
| `NoTranscriptFound` | 指定言語の字幕が見つからない |
| `TranscriptsDisabled` | 動画の字幕機能が無効化されている |
| `YouTubeRequestFailed` | YouTubeへのリクエスト失敗（汎用） |
| `RequestBlocked` | リクエストがブロックされた（IP制限等） |

いずれも `youtube_transcript_api` からインポート可能。

## APIレスポンス仕様（変更後）

### 成功時

```json
{
  "success": true,
  "status": "ok",
  "message": "Successfully retrieved data.",
  "error_code": null,

  "title": "動画タイトル",
  "channel_name": "チャンネル名",
  "channel_id": "UCxxxx",
  "channel_follower_count": 1250000,
  "upload_date": "2026-02-08",
  "duration": 360,
  "duration_string": "6:00",
  "view_count": 54000,
  "like_count": 1200,
  "thumbnail_url": "https://i.ytimg.com/vi/xxx/maxresdefault.jpg",
  "description": "概要欄テキスト...",
  "tags": ["Python", "Tutorial"],
  "categories": ["Education"],
  "webpage_url": "https://www.youtube.com/watch?v=xxx",

  "transcript": "[00:00:00] こんにちは...",
  "transcript_language": "ja",
  "is_generated": true
}
```

### 失敗時（字幕なし — メタデータは返す）

```json
{
  "success": false,
  "status": "error",
  "message": "この動画には利用可能な文字起こしがありませんでした。",
  "error_code": "TRANSCRIPT_NOT_FOUND",

  "title": "動画タイトル",
  "channel_name": "チャンネル名",
  "channel_id": "UCxxxx",
  "channel_follower_count": 1250000,
  "upload_date": "2026-02-08",
  "duration": 360,
  "duration_string": "6:00",
  "view_count": 54000,
  "like_count": 1200,
  "thumbnail_url": "https://i.ytimg.com/vi/xxx/...",
  "description": "概要欄テキスト...",
  "tags": ["Python", "Tutorial"],
  "categories": ["Education"],
  "webpage_url": "https://www.youtube.com/watch?v=xxx",

  "transcript": null,
  "transcript_language": null,
  "is_generated": null
}
```

### 失敗時（動画が存在しない — メタデータも取れない）

```json
{
  "success": false,
  "status": "error",
  "message": "YouTubeから情報を取得できませんでした。動画が存在しないか、非公開の可能性があります。",
  "error_code": "VIDEO_NOT_FOUND",

  "title": null,
  "channel_name": null,
  "channel_id": null,
  "channel_follower_count": null,
  "upload_date": null,
  "duration": null,
  "duration_string": null,
  "view_count": null,
  "like_count": null,
  "thumbnail_url": null,
  "description": null,
  "tags": null,
  "categories": null,
  "webpage_url": null,

  "transcript": null,
  "transcript_language": null,
  "is_generated": null
}
```

## フィールド定義

### 既存フィールド（変更なし）

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `success` | bool | 字幕取得に成功したか（このAPIの存在意義は字幕取得であるため、字幕が取れない＝失敗） |
| `message` | string | 処理結果の説明メッセージ |
| `title` | string \| null | 動画タイトル |
| `channel_name` | string \| null | チャンネル名 |
| `transcript` | string \| null | タイムスタンプ付き文字起こし全文 |

### 新規フィールド（iPhoneショートカット対応）

| フィールド | 型 | 取得元 | 説明 |
|-----------|-----|--------|------|
| `status` | string | 内部判定 | `"ok"` または `"error"`。iPhoneの言語設定に依存しない文字列での成功/失敗判定用。`success` と同じ意味だが、bool値のローカライズ問題を回避する |

### 新規フィールド（安定性 高）

| フィールド | 型 | 取得元 | yt-dlpキー名 | 説明 |
|-----------|-----|--------|-------------|------|
| `error_code` | string \| null | 内部判定 | — | プログラムで判別可能なエラー種別 |
| `upload_date` | string \| null | yt-dlp | `upload_date` | 投稿日（ISO 8601形式: YYYY-MM-DD）。yt-dlpはYYYYMMDD形式で返すため、サービス層でハイフン挿入変換を行う |
| `duration` | int \| null | yt-dlp | `duration` | 動画の長さ（秒） |
| `duration_string` | string \| null | yt-dlp | `duration_string` | 動画の長さ（"6:00"形式） |
| `view_count` | int \| null | yt-dlp | `view_count` | 再生回数 |
| `thumbnail_url` | string \| null | yt-dlp（主）/ oEmbed（フォールバック） | `thumbnail` | サムネイルURL。yt-dlpのキー名は `thumbnail`（`thumbnail_url` ではない）。oEmbedでは `thumbnail_url` |
| `description` | string \| null | yt-dlp | `description` | 概要欄テキスト |
| `tags` | list \| null | yt-dlp | `tags` | タグ一覧 |
| `categories` | list \| null | yt-dlp | `categories` | カテゴリ一覧 |
| `channel_id` | string \| null | yt-dlp | `channel_id` | チャンネルID |
| `webpage_url` | string \| null | yt-dlp | `webpage_url` | 正規化された動画URL |
| `transcript_language` | string \| null | youtube-transcript-api | — | 取得できた字幕の言語コード。`Transcript.language_code` から取得 |
| `is_generated` | bool \| null | youtube-transcript-api | — | 自動生成字幕かどうか。`Transcript.is_generated` から取得 |

### 新規フィールド（安定性 中 — 取得できない場合はnull）

| フィールド | 型 | 取得元 | yt-dlpキー名 | 説明 |
|-----------|-----|--------|-------------|------|
| `like_count` | int \| null | yt-dlp | `like_count` | 高評価数（非表示の動画ではnull） |
| `channel_follower_count` | int \| null | yt-dlp | `channel_follower_count` | チャンネル登録者数（取得不可の場合null） |

### yt-dlpの戻り値に関する注意

- yt-dlpの `extract_info` が返すdictのキーは**存在が保証されない**（動画種別・取得可否により変動する）
- すべてのフィールドは `info.get("key")` で取得し、キーが存在しない場合は `null` を返す
- `ydl.sanitize_info(info)` を通してからフィールドを取得することが推奨されている

## エラーコード定義

| error_code | 意味 | success | status |
|-----------|------|---------|--------|
| `null` | エラーなし | `true` | `"ok"` |
| `INVALID_URL` | YouTube URLとして認識できない | `false` | `"error"` |
| `VIDEO_NOT_FOUND` | 動画が存在しない・非公開・削除済み | `false` | `"error"` |
| `TRANSCRIPT_NOT_FOUND` | 指定言語の字幕が見つからない（メタデータは取得済み） | `false` | `"error"` |
| `TRANSCRIPT_DISABLED` | 動画の字幕機能が無効化されている（メタデータは取得済み） | `false` | `"error"` |
| `RATE_LIMITED` | YouTubeへのリクエスト過多・IPブロック | `false` | `"error"` |
| `METADATA_FAILED` | yt-dlpによるメタデータ取得に失敗（oEmbedにフォールバック済み） | `true`（字幕が取れていれば） | `"ok"` |
| `INTERNAL_ERROR` | 予期せぬエラー | `false` | `"error"` |

### yt-dlp の例外とerror_codeのマッピング

| 例外クラス | インポートパス | マッピング先 |
|-----------|-------------|------------|
| `DownloadError` | `yt_dlp.utils.DownloadError` | `METADATA_FAILED`（字幕成功時）または `VIDEO_NOT_FOUND`（全体失敗時） |
| `ExtractorError` | `yt_dlp.utils.ExtractorError` | `DownloadError` にラップされて伝播するため、通常は `DownloadError` で捕捉 |

### youtube-transcript-api の例外とerror_codeのマッピング

| 例外クラス | インポートパス | マッピング先 |
|-----------|-------------|------------|
| `NoTranscriptFound` | `youtube_transcript_api.NoTranscriptFound` | `TRANSCRIPT_NOT_FOUND` |
| `TranscriptsDisabled` | `youtube_transcript_api.TranscriptsDisabled` | `TRANSCRIPT_DISABLED` |
| `YouTubeRequestFailed` | `youtube_transcript_api.YouTubeRequestFailed` | `RATE_LIMITED` |
| `RequestBlocked` | `youtube_transcript_api.RequestBlocked` | `RATE_LIMITED` |

## 設計上の注意

### 取得順序（正常時）

1. **yt-dlp** で全メタデータを一括取得（title, channel_name 含む）
2. **youtube-transcript-api** で字幕を取得（`list()` → `find_transcript()` → `fetch()`）
3. レスポンスを組み立てて返す

### フォールバック（yt-dlp失敗時）

1. yt-dlpが失敗 → **oEmbed API** で最低限のメタデータ（title, channel_name, thumbnail_url）を取得
2. youtube-transcript-apiで字幕を取得
3. yt-dlp由来のフィールド（upload_date, duration等）はnullで返す

### 安定性 中のフィールドの扱い

`like_count`, `channel_follower_count` はYouTube側で非表示に設定されている場合があるため、取得できなくても正常動作とする（nullを返す）。

### 常時稼働サーバーとしての考慮

- yt-dlpの呼び出しにはレート制御を意識する
- yt-dlpはYouTubeの仕様変更に追従するため定期的な更新が必要（Dockerイメージビルド時に最新版を取得する運用が望ましい）
- Docker環境にDeno（JavaScriptランタイム）のインストールが必要（yt-dlp 2025.11.12以降のYouTube対応に必須）
