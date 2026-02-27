# 要件定義書: YouTube Data API v3 移行

## 概要

YouTube Summary APIのメタデータ取得手段を、非公式の yt-dlp から公式の YouTube Data API v3 に移行し、Bot検知によるレート制限問題を根本的に解消する。

**最重要方針: 後方互換性** — 既存のAPIレスポンス構造は一切変更しない。全フィールド名・型・意味はそのまま維持し、yt-dlp から YouTube Data API v3 への切り替えはサービス層内部の変更のみとする。APIを呼び出すiPhoneショートカット等の既存クライアントに影響を与えない。

## 背景

### 現状アーキテクチャ（feature/api-enhancements ブランチ）

- メタデータ取得: **yt-dlp の `extract_info`** を使用（oEmbed APIはフォールバック）
- 字幕取得: **youtube-transcript-api** を使用（これは変更しない）
- Docker Compose + Tailscaleネットワーク上で常時稼働中

### 解決すべき課題

yt-dlp の `extract_info` は1回の呼び出しで YouTube に対して複数の HTTP リクエストを内部的に送信する（動画ページ取得、プレイヤーJS解析、内部APIリクエスト等）。これにより、短時間に数十件のリクエストを処理すると **YouTube 側のBot検知に引っかかり、メタデータも字幕も取得できなくなる**。

- **2026-02-14**: 約20件処理後にブロックされ、以降のリクエストが全て失敗
- yt-dlp 導入前（oEmbed API 使用時）にはレート制限に遭遇したことはなかった

### YouTube Data API v3 への移行根拠

| 観点 | yt-dlp（現状） | YouTube Data API v3 |
|------|---------------|---------------------|
| 公式/非公式 | 非公式（スクレイピング） | **Google公式API** |
| レート制限 | 不明確、Bot検知で突然ブロック | **日10,000ユニット（明確なクォータ制）** |
| 1動画あたりのHTTPリクエスト数 | 内部で複数回 | **1回** |
| 認証 | 不要 | APIキー必要（無料で取得可） |
| YouTubeの仕様変更への影響 | yt-dlp更新が必要 | **公式のため安定** |

## 用語集

- **YouTube Data API v3**: Googleが提供するYouTubeの公式REST API。動画・チャンネル・プレイリスト等の情報を取得可能
- **videos.list**: YouTube Data API v3のエンドポイント。動画のメタデータ（snippet, contentDetails, statistics）を取得する。クォータコスト1ユニット
- **channels.list**: YouTube Data API v3のエンドポイント。チャンネルの統計情報（subscriberCount等）を取得する。クォータコスト1ユニット
- **クォータ（Quota）**: YouTube Data API v3の日次利用上限。デフォルト10,000ユニット/日。太平洋時間午前0時にリセット
- **part パラメータ**: API呼び出し時に取得するリソースのセクションを指定するパラメータ（例: `snippet`, `contentDetails`, `statistics`）
- **ISO 8601 Duration**: 時間長を表す国際規格の形式。`PT1H2M3S` は「1時間2分3秒」を意味する
- **oEmbed API**: YouTubeが提供する簡易メタデータ取得API。title, channel_name, thumbnail_url のみ取得可能。認証不要
- **error_code**: 本APIが返すプログラム判別可能なエラー種別文字列（`app/core/constants.py` で定義）
- **API_KEY**: 本API自体へのアクセス認証に使用する環境変数（`app/core/security.py` で `X-API-KEY` ヘッダー検証に使用）。`YOUTUBE_API_KEY` とは用途が異なる
- **YOUTUBE_API_KEY**: YouTube Data API v3 の呼び出しに使用する環境変数。Google Cloud Console で発行したAPIキーを格納する。`API_KEY`（自API認証用）とは完全に独立

## 要件

### 要件1: YouTube Data API v3 によるメタデータ取得（US-1）

**ユーザーストーリー:** iPhoneショートカットのユーザーとして、メタデータ取得が公式APIを通じて行われることで、短時間に多数のリクエストを送ってもレート制限でブロックされないようにしたい。

#### 受入基準

1. WHEN ユーザーが動画URLを送信したとき、THE System SHALL YouTube Data API v3 の `videos.list`（`part=snippet,contentDetails,statistics`）を使用してメタデータを取得する
2. WHEN メタデータ取得が成功したとき、THE System SHALL `videos.list` のレスポンスからすべての必要フィールドを抽出し、フィールドマッピング仕様に従って変換する
3. WHEN メタデータ取得が成功し、`channel_id` が取得できたとき、THE System SHALL 要件3の受入基準に従い `channels.list` で `subscriberCount` を取得する
4. THE System SHALL yt-dlp への依存を完全に削除する（`requirements.txt`、`app/services/youtube.py`、`app/core/constants.py` の `YTDLP_*` 定数）
5. THE System SHALL HTTPクライアントとして既存の `requests` ライブラリを使用し、新規依存を追加しない
6. WHEN API呼び出しを行うとき、THE System SHALL 接続タイムアウト3秒、読み取りタイムアウト10秒を設定する（`requests.get(url, timeout=(3.05, 10))`）

### 要件2: 既存全フィールドの後方互換性（US-2）

**ユーザーストーリー:** iPhoneショートカットのユーザーとして、API移行後も現在取得できている全ての情報が同じ形式で返されることで、iPhoneショートカットの修正が一切不要にしたい。

#### 受入基準

1. THE System SHALL `SummaryResponse` モデル（`app/models/schemas.py`）の全フィールド（20個の宣言フィールド + 1個の算出フィールド `status`）の名前・型・意味を一切変更しない
2. WHEN YouTube Data API v3 からメタデータを取得したとき、THE System SHALL フィールドマッピング仕様（後述）に従い、全フィールドを正確に変換する
3. WHEN 任意のフィールドがAPIレスポンスに存在しない場合、THE System SHALL デフォルト値 `None` を返す
4. THE System SHALL `upload_date` を ISO 8601 datetime（`2026-02-27T10:00:00Z`）から `YYYY-MM-DD` 形式に変換する
5. THE System SHALL `duration` を ISO 8601 duration（`PT1H2M3S`）から秒数（int）に変換する
6. THE System SHALL `duration_string` を ISO 8601 duration から `"H:MM:SS"` または `"M:SS"` 形式に変換する
7. THE System SHALL `categories` を `snippet.categoryId`（数値ID文字列）から静的マッピングテーブルで英語カテゴリ名に変換し、`[name]` のリスト形式で返す
8. THE System SHALL `thumbnail_url` を `snippet.thumbnails` から `maxres` → `standard` → `high` → `medium` → `default` の優先順で選択する
9. THE System SHALL `view_count`, `like_count`, `channel_follower_count` の文字列値を `int` に変換する
10. THE System SHALL `transcript`, `transcript_language`, `is_generated` を youtube-transcript-api から取得する処理を変更しない

### 要件3: チャンネル登録者数の取得（US-3）

**ユーザーストーリー:** iPhoneショートカットのユーザーとして、`channel_follower_count` が引き続きレスポンスに含まれることで、チャンネルの規模感を把握したい。

#### 受入基準

1. WHEN `videos.list` から `channel_id` を取得したとき、THE System SHALL `channels.list`（`part=statistics`）を呼び出し、`subscriberCount` を取得する
2. THE System SHALL `subscriberCount`（文字列）を `int` に変換して `channel_follower_count` として返す
3. IF チャンネルの `hiddenSubscriberCount` が `true` の場合、THEN THE System SHALL `channel_follower_count` に `None` を返す
4. THE System SHALL `hiddenSubscriberCount` が `true` のとき、フィールド欠損または `"0"` の両方に防御的に対応する
5. IF `channels.list` の呼び出しが失敗した場合、THEN THE System SHALL `channel_follower_count` に `None` を返し、他のフィールドの取得には影響させない

### 要件4: APIキーの安全な管理（US-4）

**ユーザーストーリー:** 開発者として、YouTube Data API v3 のAPIキーが安全に管理されることで、キーの漏洩リスクを最小限に抑えたい。

#### 受入基準

1. THE System SHALL APIキーを `.env.local` に `YOUTUBE_API_KEY` として管理する
2. THE System SHALL `.env.local` が `.gitignore` に含まれていることを確認する（確認済み）
3. THE System SHALL `.env.example` に `YOUTUBE_API_KEY` のプレースホルダーをコメントで追加し、「`.env.local`で設定すること」と明記する
4. WHEN `YOUTUBE_API_KEY` が環境変数に設定されていない場合、THE System SHALL リクエスト処理時に `error_code: "INTERNAL_ERROR"` と明確なエラーメッセージを返す
5. THE System SHALL APIキーがログ出力に漏洩しないよう、URLクエリパラメータを含むURLのログ出力を禁止する
6. WHEN Docker Compose が起動するとき、THE System SHALL 既存の `env_file` パターン（`.env` は `required: true`、`.env.local` は `required: false`）でAPIキーを読み込む

### 要件5: クォータ超過時のエラーハンドリング（US-5）

**ユーザーストーリー:** iPhoneショートカットのユーザーとして、YouTube APIのクォータ超過時に明確なエラーが返されることで、「なぜ失敗したか」が分かり翌日に再試行すればよいと判断したい。

#### 受入基準

1. WHEN YouTube Data API v3 が HTTP 403（`reason: "quotaExceeded"`）を返した場合、THE System SHALL `error_code: "RATE_LIMITED"` を返す
2. WHEN クォータ超過エラーが発生した場合、THE System SHALL `message` にクォータ超過であることを示すメッセージを含める
3. THE System SHALL エラーハンドリング仕様（後述）に従い、全APIエラーを適切な `error_code` にマッピングする

### 要件6: フォールバック戦略（US-6）

**ユーザーストーリー:** iPhoneショートカットのユーザーとして、YouTube Data API v3 が一時的に利用できない場合でも、最低限のメタデータが返されることで、完全な失敗を回避したい。

#### 受入基準

1. WHEN YouTube Data API v3 の呼び出しがネットワークエラーまたはサーバーエラー（500/502/503/504）で失敗した場合、THE System SHALL 指数バックオフ（1秒→2秒→4秒）で最大3回リトライする（初回試行を含め合計最大4回試行）
2. WHEN リトライしても回復しない場合、THE System SHALL 既存の `_fetch_metadata_oembed` 関数にフォールバックし、最低限のメタデータ（`title`, `channel_name`, `thumbnail_url`）を取得する
3. WHEN oEmbed フォールバックが成功し、字幕も取得できた場合、THE System SHALL `error_code: "METADATA_FAILED"` を返す（既存の動作と同一）
4. THE System SHALL 4xxエラー（`badRequest`, `unauthorized`, `forbidden`, `quotaExceeded` 等）ではリトライしない

### 要件7: 依存関係と Docker 構成の更新（US-7）

**ユーザーストーリー:** 開発者として、不要になった依存関係を削除しDocker構成を簡素化することで、コンテナイメージの軽量化と保守性の向上を実現したい。

#### 受入基準

1. THE System SHALL `requirements.txt` から `yt-dlp` を削除する
2. THE System SHALL `docker/Dockerfile.api` から Deno のインストール処理を削除する
3. THE System SHALL `app/services/youtube.py` から `yt_dlp` の import と `_fetch_metadata_ytdlp`, `_build_metadata_from_ytdlp` 関数を削除する
4. THE System SHALL `app/core/constants.py` から `YTDLP_KEY_MAP`, `YTDLP_DIRECT_KEYS` 定数を削除する
5. THE System SHALL 新規依存を追加しない（`requests` は既に導入済み）

## フィールドマッピング仕様

`SummaryResponse` モデルの全21プロパティ（20個の宣言フィールド + 1個の算出フィールド `status`）について、変換元・変換処理・デフォルト値を定義する。

> **注記**: `success`, `message`, `status` はAPI処理結果の制御フィールドであり、外部APIからの変換対象ではない。これらは既存ロジックで内部判定されるため、本移行の変換対象外とする。移行で変換が必要な14フィールド + 変更なしの字幕3フィールド + エラー制御1フィールドを以下に定義する。

### メタデータフィールド（YouTube Data API v3 から取得）

| # | レスポンスフィールド | 型 | API / パート | APIフィールド | 変換処理 | 欠損時のデフォルト |
|---|---------------------|-----|-------------|--------------|---------|-------------------|
| 1 | `title` | `str \| None` | videos.list / snippet | `snippet.title` | そのまま | `None` |
| 2 | `channel_name` | `str \| None` | videos.list / snippet | `snippet.channelTitle` | そのまま | `None` |
| 3 | `channel_id` | `str \| None` | videos.list / snippet | `snippet.channelId` | そのまま | `None` |
| 4 | `upload_date` | `str \| None` | videos.list / snippet | `snippet.publishedAt` | ISO 8601 datetime → `YYYY-MM-DD` 切り出し（UTC前提で日付部分のみ取得） | `None` |
| 5 | `duration` | `int \| None` | videos.list / contentDetails | `contentDetails.duration` | ISO 8601 duration（`PT1H2M3S`）→ 秒数（int）。正規表現で `P(\d+D)?T?(\d+H)?(\d+M)?(\d+S)?` をパース | `None` |
| 6 | `duration_string` | `str \| None` | videos.list / contentDetails | `contentDetails.duration` | ISO 8601 duration → `"H:MM:SS"`（1時間以上）/ `"M:SS"`（1時間未満）形式 | `None` |
| 7 | `view_count` | `int \| None` | videos.list / statistics | `statistics.viewCount` | `int(str)` | `None` |
| 8 | `like_count` | `int \| None` | videos.list / statistics | `statistics.likeCount` | `int(str)`。**フィールド自体が省略される場合あり** → `.get("likeCount")` で `None` を許容 | `None` |
| 9 | `thumbnail_url` | `str \| None` | videos.list / snippet | `snippet.thumbnails` | `maxres` → `standard` → `high` → `medium` → `default` の優先順でURLを選択 | `None` |
| 10 | `description` | `str \| None` | videos.list / snippet | `snippet.description` | そのまま | `None` |
| 11 | `tags` | `list[str] \| None` | videos.list / snippet | `snippet.tags` | そのまま。**フィールド自体が存在しない場合あり** → `.get("tags")` で `None` を返す | `None` |
| 12 | `categories` | `list[str] \| None` | videos.list / snippet | `snippet.categoryId` | 静的マッピングテーブル（`YOUTUBE_CATEGORY_MAP`）で名前に変換 → `[name]` のリスト形式。未知IDはそのまま文字列で返す | `None` |
| 13 | `webpage_url` | `str \| None` | — | — | `https://www.youtube.com/watch?v={video_id}` を構築 | `None` |
| 14 | `channel_follower_count` | `int \| None` | channels.list / statistics | `statistics.subscriberCount` | `int(str)`。`hiddenSubscriberCount` が `true` の場合は `None` | `None` |

### 字幕フィールド（youtube-transcript-api から取得 — 変更なし）

| # | レスポンスフィールド | 型 | 取得元 | 変換処理 |
|---|---------------------|-----|--------|---------|
| 15 | `transcript` | `str \| None` | youtube-transcript-api | タイムスタンプ付きテキスト（既存処理を維持） |
| 16 | `transcript_language` | `str \| None` | youtube-transcript-api | `fetched.language_code`（既存処理を維持） |
| 17 | `is_generated` | `bool \| None` | youtube-transcript-api | `fetched.is_generated`（既存処理を維持） |

### 制御フィールド（内部判定 — 本移行の変換対象外）

| # | レスポンスフィールド | 型 | 説明 |
|---|---------------------|-----|------|
| 18 | `success` | `bool` | 字幕取得の成否。既存ロジックで判定（変更なし） |
| 19 | `message` | `str` | 処理結果メッセージ。`app/core/constants.py` の `MSG_*` 定数を使用（変更なし） |
| 20 | `error_code` | `str \| None` | プログラムで判別可能なエラー種別。`app/core/constants.py` の `ERROR_*` 定数を使用 |
| 21 | `status` | `str` | `@computed_field` — `success` から自動算出（`"ok"` / `"error"`）。変更なし |

## エラーハンドリング仕様

YouTube Data API v3 のエラーレスポンスを本APIの `error_code` にマッピングする。

### エラーレスポンス共通構造（YouTube Data API v3）

```json
{
  "error": {
    "code": "<HTTPステータスコード>",
    "message": "<メッセージ>",
    "errors": [
      {
        "message": "<詳細>",
        "domain": "<ドメイン>",
        "reason": "<理由コード>"
      }
    ]
  }
}
```

### エラー分類とマッピング

| HTTP | reason | 意味 | アプリの error_code | リトライ |
|------|--------|------|-------------------|---------|
| 200 | items: [] | 動画なし/非公開/削除済み | `VIDEO_NOT_FOUND` | 不可 |
| 400 | `badRequest` | パラメータ不正 | `INTERNAL_ERROR` | 不可 |
| 401 | `unauthorized` | 認証エラー | `INTERNAL_ERROR` | 不可 |
| 403 | `quotaExceeded` | クォータ超過 | `RATE_LIMITED` | 不可（リセット待ち） |
| 403 | `forbidden` | 権限不足 | `VIDEO_NOT_FOUND` | 不可 |
| 403 | `accessNotConfigured` | API未有効化 | `INTERNAL_ERROR` | 不可 |
| 404 | `notFound` | リソースなし | `VIDEO_NOT_FOUND` | 不可 |
| 500 | `backendError` | サーバー障害 | （リトライ後）`METADATA_FAILED` | **指数バックオフ** |
| 502 | — | Bad Gateway | （リトライ後）`METADATA_FAILED` | **指数バックオフ** |
| 503 | — | サービス停止 | （リトライ後）`METADATA_FAILED` | **指数バックオフ** |
| 504 | — | Gateway Timeout | （リトライ後）`METADATA_FAILED` | **指数バックオフ** |

### リトライ戦略

- 対象: HTTP 500, 502, 503, 504 のみ
- 指数バックオフ: 1秒 → 2秒 → 4秒（最大3回リトライ、初回含め合計4回試行）
- 4xxエラーは即時失敗（リトライ不可）

## 非機能要件

### パフォーマンス

1. WHEN 1動画のメタデータを取得するとき、THE System SHALL YouTube Data API v3 への呼び出しを最大2回（`videos.list` + `channels.list`）に抑える
2. THE System SHALL API呼び出しの接続タイムアウトを3秒、読み取りタイムアウトを10秒に設定する
3. THE System SHALL 平常時（リトライなし）の1動画あたりメタデータ取得処理を30秒以内に完了する
4. THE System SHALL 障害時（リトライ含む）の1動画あたりメタデータ取得処理を100秒以内に完了する（最悪ケース: 2エンドポイント ×（4回試行 × 読み取り10秒 + バックオフ7秒）= 2 × 47 = 94秒）

### セキュリティ

1. THE System SHALL APIキーを環境変数（`os.getenv("YOUTUBE_API_KEY")`）から読み込む
2. THE System SHALL APIキーを含むURLをログに出力しない
3. THE System SHALL `requests.get()` で `verify=False` を設定しない（デフォルトのSSL証明書検証を維持）
4. THE System SHALL APIキー制限として、Google Cloud Console で YouTube Data API v3 のみに制限することを推奨する

### 可用性

1. THE System SHALL YouTube Data API v3 の障害時に oEmbed API へフォールバックし、最低限のメタデータを返す
2. THE System SHALL 1日あたり最大5,000動画の処理が可能である（クォータ10,000ユニット、1動画2ユニット）

### 保守性

1. THE System SHALL API URL テンプレート、カテゴリマッピング、タイムアウト値等の定数を `app/core/constants.py` に集約する
2. THE System SHALL 新規に追加するエラーメッセージを `app/core/constants.py` の `ERROR_CODE_TO_MESSAGE` マッピングに追加する
3. THE System SHALL YouTube Data API v3 関連の処理を `app/services/youtube.py` 内に集約し、他モジュールへの影響を最小化する

## スコープ外

以下の項目は本移行のスコープ外とする：

- youtube-transcript-api の変更（字幕取得ロジックは現状維持）
- APIエンドポイントのURL変更（`/summary` は変更なし）
- レスポンスフィールドの追加・削除（全フィールドの名前・型・意味を維持）
- iPhoneショートカット側の変更
- OAuth 2.0 認証の導入（APIキー認証で十分）
- クォータ引き上げ申請（現在の利用量では不要）
- YouTube Data API v3 のレスポンスキャッシュ（将来検討事項）
- `videoCategories.list` API によるカテゴリ名の動的取得（静的マッピングで対応）

## 技術的決定事項

### 決定事項1: `requests` による REST API 直接呼び出し

**採用理由:**
- `requests==2.32.4` は既に `requirements.txt` に含まれており、依存追加ゼロ
- 1日最大50件、同期サービス層、エンドポイント2つのみの規模に適合
- `google-api-python-client` は50MB超の依存増でDockerイメージが肥大化する
- タイムアウト・リトライ・エラーハンドリングを明示的に記述可能

**排除した代替案:**
- **`google-api-python-client`**: 50MB超の依存追加。本プロジェクトの規模（エンドポイント2つ）には過剰。Dockerイメージの肥大化を招く
- **`httpx`**: 非同期対応は不要（現在の同期サービス層で十分）。新規依存追加が必要

### 決定事項2: 静的カテゴリマッピングテーブル

**採用理由:**
- YouTubeのカテゴリIDは2012年頃からほぼ変更なしで非常に安定
- `videoCategories.list` はクォータ1ユニットを消費 + ネットワークレイテンシ増
- yt-dlp が英語名で返していたため、英語名（US基準）の静的マッピングで後方互換性を維持

**排除した代替案:**
- **`videoCategories.list` API で動的取得**: クォータ消費（1ユニット/リクエスト）とレイテンシ増。`regionCode` パラメータによりカテゴリのサブセットが変わる問題もある
- **カテゴリIDをそのまま返す**: 既存レスポンス（`["Education"]` 等のカテゴリ名リスト）との後方互換性が崩れる

### 決定事項3: ISO 8601 Duration の正規表現パース

**採用理由:**
- YouTube Data API v3 が返す duration は ISO 8601 の限定サブセット（`P#DT#H#M#S`）
- `P#DT#H#M#S` まで対応すれば十分で、正規表現で簡潔に実装可能
- `isodate` ライブラリは追加依存になり、この用途には過剰

**対応すべきパターン:**

| 入力 | 秒数 | 文字列表示 |
|------|------|-----------|
| `PT1H2M3S` | 3723 | `"1:02:03"` |
| `PT30S` | 30 | `"0:30"` |
| `PT10M` | 600 | `"10:00"` |
| `P0D` | 0 | `"0:00"` |
| `PT0S` | 0 | `"0:00"` |
| `P1DT2H3M4S` | 93784 | `"26:03:04"` |

## 技術的制約（専門家調査結果）

> 調査日: 2026-02-27
> 回答者: 専門家O（アーキテクト）、専門家A（Web検索確認済）、専門家G（AI調査）
> 信頼度: 以下の情報は3名の専門家の合意、および公式ドキュメントとの照合により信頼性97%以上と判断したもの

### videos.list API レスポンス仕様

- **`snippet.publishedAt`**: ISO 8601 形式、UTC（Z suffix）付き。例: `"2026-02-27T10:00:00Z"`
- **`contentDetails.duration`**: ISO 8601 duration 形式。`P0D`/`PT0S`（ライブ配信等）、`P1DT2H3M4S`（1日以上）にも対応必要
- **`statistics.*`（viewCount, likeCount 等）**: すべて文字列型（string）。64bit整数のJSON表現の都合（[Google APIs type/format](https://docs.cloud.google.com/docs/discovery/type-format)）
- **`likeCount` 非公開時**: フィールド自体がレスポンスから省略される（`null` や `"0"` ではない）
- **`snippet.tags` 未設定時**: フィールド自体がレスポンスに存在しない（空配列ではない）
- **`snippet.thumbnails` のキー**: `default`(120×90), `medium`(320×180), `high`(480×360) は全動画で存在。`standard`(640×480), `maxres`(1280×720) は存在しない場合がある
- **存在しない・非公開・削除済み動画**: HTTP 200 OK で `items` が空配列 `[]`。404にはならない

### channels.list API — subscriberCount 仕様

- `subscriberCount` の型: 文字列（string）→ `int()` 変換が必要
- `subscriberCount` は3桁の有効数字に丸められた概数（例: 登録者123,456人 → `"123000"`）
- `hiddenSubscriberCount` が `true` の場合: フィールド欠損または `"0"` の両方に対応すべき（防御的実装）

### ソース

- [Videos リソース](https://developers.google.com/youtube/v3/docs/videos)
- [Videos: list](https://developers.google.com/youtube/v3/docs/videos/list)
- [Channels リソース](https://developers.google.com/youtube/v3/docs/channels)
- [Channels: list](https://developers.google.com/youtube/v3/docs/channels/list)
- [VideoCategories: list](https://developers.google.com/youtube/v3/docs/videoCategories/list)
- [YouTube Data API Overview](https://developers.google.com/youtube/v3/getting-started)
- [Quota Calculator](https://developers.google.com/youtube/v3/determine_quota_cost)
- [Quota and Compliance Audits](https://developers.google.com/youtube/v3/guides/quota_and_compliance_audits)
- [YouTube Data API Errors](https://developers.google.com/youtube/v3/docs/errors)
- [API keys best practices](https://cloud.google.com/docs/authentication/api-keys-best-practices)
- [Google APIs Discovery type/format](https://docs.cloud.google.com/docs/discovery/type-format)

## クォータ消費見積もり

現在の利用パターン（1日数十件）での消費:

| 操作 | 1動画あたり | 1日50件の場合 | 1日の上限 |
|------|-----------|-------------|----------|
| `videos.list` | 1ユニット | 50ユニット | — |
| `channels.list` | 1ユニット | 50ユニット | — |
| **合計** | **2ユニット** | **100ユニット** | **10,000ユニット**（余裕率100倍） |

- 1日最大処理可能件数: **5,000件**
- クォータリセット: **太平洋時間（PT）午前0時**（JST: 午後5時 / 夏時間午後4時）
- クォータ引き上げ: 可能。ただし Compliance Audit（規約準拠監査）が前提

## 定数の局所化方針

### 機密値の管理（`.env.local`）

| 環境変数 | 説明 | 管理場所 |
|---------|------|---------|
| `YOUTUBE_API_KEY` | YouTube Data API v3 のAPIキー | `.env.local`（`.gitignore` 済み） |

- Docker Compose は既存の `env_file` パターンで読み込む:
  ```yaml
  env_file:
    - path: ./.env
      required: true
    - path: ./.env.local
      required: false
  ```
- `.env.example` にプレースホルダーを追加:
  ```
  # YouTube Data API v3 key (set in .env.local)
  # YOUTUBE_API_KEY=your_api_key_here
  ```

### 定数の集約（`app/core/constants.py`）

以下の定数を `app/core/constants.py` に追加する:

| 定数名 | 値 | 説明 |
|--------|-----|------|
| `YOUTUBE_API_V3_VIDEOS_URL` | `"https://www.googleapis.com/youtube/v3/videos"` | videos.list API URL |
| `YOUTUBE_API_V3_CHANNELS_URL` | `"https://www.googleapis.com/youtube/v3/channels"` | channels.list API URL |
| `YOUTUBE_API_V3_TIMEOUT` | `(3.05, 10)` | 接続/読み取りタイムアウト（秒） |
| `YOUTUBE_API_V3_MAX_RETRIES` | `3` | サーバーエラー時の最大リトライ回数（初回試行を除く。合計最大4回試行） |
| `YOUTUBE_API_V3_RETRY_STATUS_CODES` | `{500, 502, 503, 504}` | リトライ対象のHTTPステータスコード |
| `YOUTUBE_CATEGORY_MAP` | `{"1": "Film & Animation", ...}` | カテゴリID→名前の静的マッピング |
| `YOUTUBE_THUMBNAIL_PRIORITY` | `["maxres", "standard", "high", "medium", "default"]` | サムネイル解像度の優先順位 |
| `MSG_QUOTA_EXCEEDED` | `"YouTube APIの日次クォータを超過しました。..."` | クォータ超過時メッセージ |

### 削除する定数（`app/core/constants.py`）

| 定数名 | 理由 |
|--------|------|
| `YTDLP_KEY_MAP` | yt-dlp 削除に伴い不要 |
| `YTDLP_DIRECT_KEYS` | yt-dlp 削除に伴い不要 |

## 参照ドキュメント

- `docs/ユーザーストーリー_YouTube_Data_API_v3移行.md` — ユーザーストーリーと技術変更点の詳細
- `docs/expert-reviews/youtube-data-api-v3-technical-constraints.md` — 専門家調査結果（信頼度97%以上）
- `app/models/schemas.py` — `SummaryResponse` モデル定義（全21プロパティ: 宣言20 + 算出1）
- `app/core/constants.py` — 既存定数定義（エラーコード、メッセージ、yt-dlp設定）
- `app/services/youtube.py` — 現行メタデータ取得ロジック（yt-dlp + oEmbed フォールバック）
- `docker-compose.yml` — Docker Compose 構成（`env_file` パターン確認済み）
- `.kiro/specs/api-enhancements/requirements.md` — 前回の要件定義書（フィールド定義、エラーコード定義）
- `.kiro/specs/tailnet-docker-foundation/requirements.md` — Docker/Tailscale基盤の要件定義書（EARS形式パターン）
