# ユーザーストーリー: メタデータ取得をyt-dlpからYouTube Data API v3へ移行

## 概要

YouTube Summary APIのメタデータ取得手段を、非公式な yt-dlp から公式の YouTube Data API v3 に移行し、レート制限問題を根本的に解消する。

## 背景

### 現状（feature/api-enhancements ブランチ）

- メタデータ取得: **yt-dlp の `extract_info`** を使用（oEmbed APIはフォールバック）
- 字幕取得: **youtube-transcript-api** を使用（これは変更しない）
- Docker Compose + Tailscaleネットワーク上で常時稼働中

### 発生している問題

yt-dlp の `extract_info` は1回の呼び出しで YouTube に対して複数の HTTP リクエストを内部的に送信する（動画ページ取得、プレイヤーJS解析、内部APIリクエスト等）。これにより、短時間に数十件のリクエストを処理すると **YouTube 側のレート制限（Bot検知）に引っかかり、メタデータも字幕も取得できなくなる**。

- 2026-02-14: 約20件処理後にブロックされ、以降のリクエストが全て失敗
- yt-dlp 導入前（oEmbed API 使用時）にはレート制限に遭遇したことはなかった

### なぜ YouTube Data API v3 に移行するのか

| 観点 | yt-dlp（現状） | YouTube Data API v3 |
|------|---------------|---------------------|
| 公式/非公式 | 非公式（スクレイピング） | **Google公式API** |
| レート制限 | 不明確、Bot検知で突然ブロック | **日10,000ユニット（明確なクォータ制）** |
| 1動画あたりのHTTPリクエスト数 | 内部で複数回 | **1回** |
| 認証 | 不要 | APIキー必要（無料で取得可） |
| 取得できる項目 | 多い（channel_follower_count含む） | 多い（channel_follower_countは別APIで取得可） |
| YouTubeの仕様変更への影響 | yt-dlp更新が必要 | **公式のため安定** |

## 最重要方針: 後方互換性

**既存のAPIレスポンス構造は一切変更しない。**

- 全フィールド名・型・意味はそのまま維持
- yt-dlp から YouTube Data API v3 への切り替えはサービス層内部の変更のみ
- APIを呼び出すiPhoneショートカット等の既存クライアントに影響なし

## ユーザーストーリー

### US-1: レート制限を気にせずAPIを使いたい

**As a** iPhoneショートカットのユーザー
**I want** メタデータ取得が公式APIを通じて行われる
**So that** 短時間に多数のリクエストを送っても、レート制限でブロックされることがない

#### 受け入れ条件

- メタデータ取得に YouTube Data API v3（`videos.list`）を使用している
- yt-dlp への依存が削除されている
- 1日10,000件まではエラーなく動作する（公式クォータ範囲内）

### US-2: 既存の全フィールドが引き続き取得できること

**As a** iPhoneショートカットのユーザー
**I want** API移行後も、現在取得できている全ての情報が同じ形式で返される
**So that** iPhoneショートカットの修正が一切不要

#### 受け入れ条件

- 以下のフィールドが YouTube Data API v3 から取得できている:
  - `title` — `snippet.title`
  - `channel_name` — `snippet.channelTitle`
  - `channel_id` — `snippet.channelId`
  - `upload_date` — `snippet.publishedAt`（ISO 8601 → YYYY-MM-DD に変換）
  - `duration` — `contentDetails.duration`（ISO 8601 → 秒数に変換）
  - `duration_string` — `contentDetails.duration`（ISO 8601 → "M:SS" 形式に変換）
  - `view_count` — `statistics.viewCount`
  - `like_count` — `statistics.likeCount`
  - `thumbnail_url` — `snippet.thumbnails` から最適な解像度を選択
  - `description` — `snippet.description`
  - `tags` — `snippet.tags`
  - `categories` — `snippet.categoryId`（IDから名前への変換が必要か検討）
  - `webpage_url` — 動画IDから `https://www.youtube.com/watch?v={id}` を構築
- `transcript`, `transcript_language`, `is_generated` は youtube-transcript-api から取得（変更なし）

### US-3: チャンネル登録者数も引き続き取得したい

**As a** iPhoneショートカットのユーザー
**I want** `channel_follower_count` が引き続きレスポンスに含まれている
**So that** チャンネルの規模感を把握できる

#### 受け入れ条件

- `channels.list` API（`part=statistics`）を使い、`subscriberCount` を取得している
- `videos.list` と合わせて1動画あたり2ユニットのクォータ消費（1日最大5,000件）
- チャンネル登録者数が非公開の場合は `null` を返す

### US-4: APIキーを安全に管理したい

**As a** 開発者
**I want** YouTube Data API v3 の APIキーが安全に管理されている
**So that** キーの漏洩リスクを最小限に抑えられる

#### 受け入れ条件

- APIキーは `.env.local` に `YOUTUBE_API_KEY` として記載
- `.env.local` は `.gitignore` に含まれている（確認済み）
- `.env.example` にプレースホルダーが追加されている
- APIキーが未設定の場合、アプリ起動時またはリクエスト時に明確なエラーメッセージを返す

### US-5: クォータ超過時に適切なエラーを返したい

**As a** iPhoneショートカットのユーザー
**I want** YouTube APIのクォータ超過時に、レート制限と同様の明確なエラーが返される
**So that** 「なぜ失敗したか」が分かり、翌日に再試行すればよいと判断できる

#### 受け入れ条件

- YouTube Data API v3 が HTTP 403（`quotaExceeded`）を返した場合、`error_code: "RATE_LIMITED"` を返す
- `message` にクォータ超過であることを示すメッセージを含める

## 技術的な変更点

### 依存関係の変更

| 変更 | 旧 | 新 |
|------|----|----|
| メタデータ取得 | yt-dlp + oEmbed API | **YouTube Data API v3**（`google-api-python-client` または `requests` で直接呼び出し） |
| 字幕取得 | youtube-transcript-api | youtube-transcript-api（**変更なし**） |
| 削除 | yt-dlp | 依存から削除 |
| 削除 | Deno（yt-dlpのJS実行に必要だった） | Dockerfileから削除可能 |

### YouTube Data API v3 の呼び出し方法

```
GET https://www.googleapis.com/youtube/v3/videos
  ?part=snippet,contentDetails,statistics
  &id={video_id}
  &key={YOUTUBE_API_KEY}
```

```
GET https://www.googleapis.com/youtube/v3/channels
  ?part=statistics
  &id={channel_id}
  &key={YOUTUBE_API_KEY}
```

### フィールドマッピング（YouTube Data API v3 → レスポンス）

| レスポンスフィールド | API パート | APIフィールド | 変換処理 |
|---------------------|-----------|-------------|---------|
| `title` | snippet | `title` | そのまま |
| `channel_name` | snippet | `channelTitle` | そのまま |
| `channel_id` | snippet | `channelId` | そのまま |
| `upload_date` | snippet | `publishedAt` | ISO 8601 datetime → `YYYY-MM-DD` に切り出し |
| `duration` | contentDetails | `duration` | ISO 8601 duration（`PT1H2M3S`）→ 秒数（int）に変換 |
| `duration_string` | contentDetails | `duration` | ISO 8601 duration → `"1:02:03"` 形式に変換 |
| `view_count` | statistics | `viewCount` | 文字列 → int に変換 |
| `like_count` | statistics | `likeCount` | 文字列 → int に変換（非公開時は null） |
| `thumbnail_url` | snippet | `thumbnails` | maxres → standard → high → medium → default の優先順で URL を選択 |
| `description` | snippet | `description` | そのまま |
| `tags` | snippet | `tags` | そのまま（存在しない場合は null） |
| `categories` | snippet | `categoryId` | ID（文字列）をそのまま返すか、名前に変換するか要検討 |
| `webpage_url` | — | — | `https://www.youtube.com/watch?v={video_id}` を構築 |
| `channel_follower_count` | statistics（channels.list） | `subscriberCount` | 文字列 → int に変換（`hiddenSubscriberCount` が true なら null） |

### データ型の注意点

YouTube Data API v3 は数値フィールド（`viewCount`, `likeCount` 等）を**文字列として返す**ため、int への変換が必要。

### categories フィールドの扱いについて（要検討）

yt-dlp は `categories` をカテゴリ名のリスト（例: `["Education"]`）で返していたが、YouTube Data API v3 の `snippet.categoryId` は数値ID（例: `"27"`）を返す。

選択肢:
1. **カテゴリIDをそのまま返す** — シンプルだが既存と互換性なし
2. **`videoCategories.list` APIでID→名前を変換して返す** — 既存と互換性あり（追加1ユニット消費、ただしキャッシュ可能）
3. **アプリ内にマッピングテーブルを持つ** — API呼び出し不要だが、カテゴリ追加時にメンテナンスが必要

### フォールバック戦略

YouTube Data API v3 が失敗した場合（ネットワークエラー、一時障害等）:
- **oEmbed API にフォールバック**して最低限のメタデータ（title, channel_name, thumbnail_url）を取得する
- 既存の `_fetch_metadata_oembed` 関数を引き続き活用

### クォータ消費の見積もり

現在の利用パターン（1日数十件）での消費:

| 操作 | 1動画あたり | 1日50件の場合 |
|------|-----------|-------------|
| `videos.list` | 1ユニット | 50ユニット |
| `channels.list` | 1ユニット | 50ユニット |
| **合計** | **2ユニット** | **100ユニット**（上限10,000の1%） |

### Dockerfile の簡素化

yt-dlp と Deno が不要になるため、`Dockerfile.api` から以下を削除可能:
- Deno のインストール処理
- yt-dlp の pip インストール
- コンテナイメージの軽量化が見込まれる

## エラーハンドリング

### YouTube Data API v3 のエラーと error_code のマッピング

| API レスポンス | error_code | 説明 |
|---------------|-----------|------|
| 正常（items が空） | `VIDEO_NOT_FOUND` | 動画が存在しない・非公開・削除済み |
| HTTP 403 `quotaExceeded` | `RATE_LIMITED` | 日次クォータ超過 |
| HTTP 403 `forbidden` | `VIDEO_NOT_FOUND` | アクセス権なし |
| HTTP 400 `keyInvalid` | `INTERNAL_ERROR` | APIキーが無効 |
| ネットワークエラー等 | `METADATA_FAILED` | oEmbed にフォールバック |

## スコープ外

- youtube-transcript-api の変更（字幕取得ロジックは現状維持）
- APIエンドポイントのURL変更
- レスポンスフィールドの追加・削除
- iPhoneショートカット側の変更
