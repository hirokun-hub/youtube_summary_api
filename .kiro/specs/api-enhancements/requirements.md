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
| メタデータ取得 | oEmbed API のみ | **oEmbed API（軽量）+ yt-dlp（主軸）** |
| 文字起こし | youtube-transcript-api 1.1.0 | youtube-transcript-api **最新版** |
| 削除 | pytube 15.0.0 | **依存から削除** |

### yt-dlp 選定理由

- 2026年2月4日にもリリースあり。開発が非常に活発で、YouTubeの仕様変更への追従が最速
- `extract_info(url, download=False)` でダウンロードせずメタデータのみ取得可能
- 認証不要、APIキー不要、クォータ制限なし
- 専門家3名の意見が全員一致で yt-dlp を推奨

### 後方互換性

- 既存の5フィールド（`success`, `message`, `title`, `channel_name`, `transcript`）は名前・型・内容ともに変更なし
- 新規フィールドが追加されるのみ
- **iPhoneショートカット側の既存動作に影響なし**（JSONにキーが増えるだけ）
- `status`（文字列 `"ok"` / `"error"`）を新設し、iPhoneの言語設定によるbool値ローカライズ問題（日本語環境で `true` が「はい」になる等）を回避。ショートカット側では `status` の文字列比較で分岐することを推奨

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
  "upload_date": "20260208",
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
  "upload_date": "20260208",
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

| フィールド | 型 | 取得元 | 説明 |
|-----------|-----|--------|------|
| `error_code` | string \| null | 内部判定 | プログラムで判別可能なエラー種別 |
| `upload_date` | string \| null | yt-dlp | 投稿日（YYYYMMDD形式） |
| `duration` | int \| null | yt-dlp | 動画の長さ（秒） |
| `duration_string` | string \| null | yt-dlp | 動画の長さ（"6:00"形式） |
| `view_count` | int \| null | yt-dlp | 再生回数 |
| `thumbnail_url` | string \| null | oEmbed | サムネイルURL |
| `description` | string \| null | yt-dlp | 概要欄テキスト |
| `tags` | list \| null | yt-dlp | タグ一覧 |
| `categories` | list \| null | yt-dlp | カテゴリ一覧 |
| `channel_id` | string \| null | yt-dlp | チャンネルID |
| `webpage_url` | string \| null | yt-dlp | 正規化された動画URL |
| `transcript_language` | string \| null | youtube-transcript-api | 取得できた字幕の言語コード |
| `is_generated` | bool \| null | youtube-transcript-api | 自動生成字幕かどうか |

### 新規フィールド（安定性 中 — 取得できない場合はnull）

| フィールド | 型 | 取得元 | 説明 |
|-----------|-----|--------|------|
| `like_count` | int \| null | yt-dlp | 高評価数（非表示の動画ではnull） |
| `channel_follower_count` | int \| null | yt-dlp | チャンネル登録者数（取得不可の場合null） |

## エラーコード定義

| error_code | 意味 | success | status |
|-----------|------|---------|--------|
| `null` | エラーなし | `true` | `"ok"` |
| `INVALID_URL` | YouTube URLとして認識できない | `false` | `"error"` |
| `VIDEO_NOT_FOUND` | 動画が存在しない・非公開・削除済み | `false` | `"error"` |
| `TRANSCRIPT_NOT_FOUND` | 字幕が見つからない（メタデータは取得済み） | `false` | `"error"` |
| `RATE_LIMITED` | YouTubeへのリクエスト過多 | `false` | `"error"` |
| `METADATA_FAILED` | yt-dlpによるメタデータ取得に失敗（oEmbedにフォールバック） | `true` | `"ok"` |
| `INTERNAL_ERROR` | 予期せぬエラー | `false` | `"error"` |

## 設計上の注意

### 取得順序とフォールバック

1. **oEmbed API**（軽量・高速）→ title, channel_name, thumbnail_url
2. **yt-dlp**（重いがメタデータ豊富）→ upload_date, duration, view_count 等
3. **youtube-transcript-api**（字幕専用）→ transcript, transcript_language, is_generated

yt-dlpが失敗しても、oEmbed + transcript で最低限のレスポンスは返す。

### 安定性 中のフィールドの扱い

`like_count`, `channel_follower_count` はYouTube側で非表示に設定されている場合があるため、取得できなくても正常動作とする（nullを返す）。

### 常時稼働サーバーとしての考慮

- yt-dlpの呼び出しにはレート制御を意識する
- yt-dlpはYouTubeの仕様変更に追従するため定期的な更新が必要（Dockerイメージビルド時に最新版を取得する運用が望ましい）
