# YouTube Summary API

YouTube 動画のメタデータ・字幕取得 (`/api/v1/summary`) と検索 (`/api/v1/search`) を提供する FastAPI サーバーです。Docker Compose で常駐し、ホスト側 Tailscale 経由で Tailnet 内にプライベート公開して運用します。

## 機能

- **動画詳細取得 (`/api/v1/summary`)**: YouTube Data API v3 + oEmbed フォールバックでメタデータ、`youtube-transcript-api` で字幕を取得
- **検索エンドポイント (`/api/v1/search`)**: 信憑性指標 (`like_view_ratio` / `comment_view_ratio` / `channel_avg_views` 等) 付きの検索結果を最大 50 件返却
- **クォータ追跡 (`quota` フィールド)**: 全レスポンスに本日消費 units、残量推定、PT 0:00 までのリセット秒数を同梱
- **永続化された使用履歴**: SQLite (WAL mode) に全 API 呼び出しを記録、プロセス再起動後に `consumed_units_today` を SUM で復元
- **二系統のレート制限**: `/summary` (60 秒最低間隔) と `/search` (60 秒/10 リクエストのスライディングウィンドウ)
- **HTTP ステータス正規化** (`/search` のみ): 200 / 401 / 422 / 429 / 503 / 500 を error_code に対応付け
- **Tailnet 経由のセキュアなアクセス**
- **iPhone ショートカット後方互換**: `/summary` の既存 22 フィールドは完全維持、`quota` のみ追加

## API リファレンス

### `POST /api/v1/summary`

YouTube 動画 URL からメタデータと字幕を返します。**HTTP は常に 200**（既存挙動・iPhone ショートカット互換のため）。

#### リクエスト

```bash
curl -X POST http://<host>:10000/api/v1/summary \
  -H "Content-Type: application/json" \
  -H "X-API-KEY: your-api-key" \
  -d '{"url": "https://www.youtube.com/watch?v=xxxxx"}'
```

#### レスポンスフィールド

| フィールド | 型 | 説明 |
|---|---|---|
| `success` | bool | 字幕取得に成功したか |
| `status` | string | `"ok"` / `"error"` |
| `message` | string | 処理結果の説明 |
| `error_code` | string \| null | エラー種別コード |
| `title` | string \| null | 動画タイトル |
| `channel_name` | string \| null | チャンネル名 |
| `channel_id` | string \| null | チャンネル ID |
| `channel_follower_count` | int \| null | チャンネル登録者数 |
| `upload_date` | string \| null | 投稿日 (YYYY-MM-DD) |
| `duration` | int \| null | 動画の長さ（秒） |
| `duration_string` | string \| null | 動画の長さ ("6:00" 形式) |
| `view_count` | int \| null | 再生回数 |
| `like_count` | int \| null | 高評価数 |
| `thumbnail_url` | string \| null | サムネイル URL |
| `description` | string \| null | 概要欄テキスト |
| `tags` | list[str] \| null | タグ一覧 |
| `categories` | list[str] \| null | カテゴリ一覧 |
| `webpage_url` | string \| null | 正規化された動画 URL |
| `transcript` | string \| null | タイムスタンプ付き文字起こし全文 |
| `transcript_language` | string \| null | 取得した字幕の言語コード |
| `is_generated` | bool \| null | 自動生成字幕かどうか |
| `retry_after` | int \| null | クライアント側レート制限時のみ |
| `quota` | object \| null | API クォータ状態（業務処理を通った場合に付与）— [Quota フィールド](#quota-オブジェクト) を参照 |

#### レスポンス例（成功）

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
  "is_generated": true,
  "quota": {
    "consumed_units_today": 1228,
    "daily_limit": 10000,
    "last_call_cost": 2,
    "remaining_units_estimate": 8772,
    "reset_at_utc": "2026-04-26T07:00:00Z",
    "reset_at_jst": "2026-04-26T16:00:00+09:00",
    "reset_in_seconds": 18324
  }
}
```

---

### `POST /api/v1/search`

検索クエリから動画一覧 (最大 50 件) を信憑性指標付きで返します。**HTTP ステータスを正規化**（200/401/422/429/503/500）。

#### リクエスト

```bash
curl -X POST http://<host>:10000/api/v1/search \
  -H "Content-Type: application/json" \
  -H "X-API-KEY: your-api-key" \
  -d '{"q": "FastAPI tutorial"}'
```

#### リクエストフィールド

| フィールド | 型 | 必須 | 説明 |
|---|---|---|---|
| `q` | string | ✓ | 検索クエリ（空白のみは不可） |
| `order` | string | — | `relevance` / `date` / `rating` / `viewCount` / `title` |
| `published_after` | datetime | — | この日時以降に投稿された動画のみ（RFC 3339 / TZ aware） |
| `published_before` | datetime | — | この日時以前に投稿された動画のみ（RFC 3339 / TZ aware） |
| `video_duration` | string | — | `any` / `short` / `medium` / `long` |
| `region_code` | string | — | ISO 3166-1 alpha-2（例: `JP`, `US`） |
| `relevance_language` | string | — | ISO 639-1（例: `ja`, `en`） |
| `channel_id` | string | — | 特定チャンネル内検索 |

#### レスポンスフィールド (`results[]` の各要素)

| フィールド | 型 | 説明 |
|---|---|---|
| `video_id` | string | YouTube 動画 ID |
| `title` | string | 動画タイトル |
| `channel_name` | string | チャンネル名 |
| `channel_id` | string | チャンネル ID |
| `upload_date` | string \| null | 投稿日 (YYYY-MM-DD) |
| `thumbnail_url` | string \| null | サムネイル URL |
| `webpage_url` | string | 動画 URL |
| `description` | string | 概要欄テキスト |
| `tags` | list[str] \| null | タグ一覧 |
| `category` | string \| null | カテゴリ名 |
| `duration` | int \| null | 動画の長さ（秒） |
| `duration_string` | string \| null | 動画の長さ ("mm:ss" 形式) |
| `has_caption` | bool | 字幕の有無（`contentDetails.caption` 由来） |
| `definition` | string \| null | 動画品質 (`hd` / `sd`) |
| `view_count` | int \| null | 再生回数 |
| `like_count` | int \| null | 高評価数 |
| `like_view_ratio` | float \| null | `like_count / view_count`（分母 0 で null） |
| `comment_count` | int \| null | コメント数 |
| `comment_view_ratio` | float \| null | `comment_count / view_count` |
| `channel_follower_count` | int \| null | チャンネル登録者数 |
| `channel_video_count` | int \| null | チャンネル動画総数 |
| `channel_total_view_count` | int \| null | チャンネル累計再生数 |
| `channel_created_at` | string \| null | チャンネル作成日 (YYYY-MM-DD) |
| `channel_avg_views` | int \| null | チャンネル動画あたり平均再生数 |

> **注**: `transcript` / `transcript_language` / `is_generated` は `/search` には **含まれません**（最大 50 件取得時のクォータ消費を抑えるため）。字幕が必要な動画は `has_caption: true` を確認してから `/summary` を呼び出してください。

#### レスポンス例（成功）

```json
{
  "success": true,
  "status": "ok",
  "message": "Successfully retrieved search results.",
  "error_code": null,
  "query": "FastAPI tutorial",
  "total_results_estimate": 138293,
  "returned_count": 50,
  "results": [ /* SearchResult x 50 */ ],
  "retry_after": null,
  "quota": {
    "consumed_units_today": 1330,
    "daily_limit": 10000,
    "last_call_cost": 102,
    "remaining_units_estimate": 8670,
    "reset_at_utc": "2026-04-26T07:00:00Z",
    "reset_at_jst": "2026-04-26T16:00:00+09:00",
    "reset_in_seconds": 18324
  }
}
```

#### レスポンス例（クライアント側レート制限超過）

```json
{
  "success": false,
  "status": "error",
  "message": "Search rate limit exceeded: more than 10 requests in the last 60 seconds. Rule: max 10 requests per 60 seconds. Retry after 52 seconds.",
  "error_code": "CLIENT_RATE_LIMITED",
  "query": "x",
  "retry_after": 52,
  "quota": { /* ... */ }
}
```
HTTP `429`、`Retry-After: 52` ヘッダ付き。

---

### `quota` オブジェクト

`/summary` (業務処理通過時) と `/search` (200/429/503/500) のレスポンスに同梱されます。`/search` の 401/422 では含まれません。

| フィールド | 型 | 説明 |
|---|---|---|
| `consumed_units_today` | int | 本日消費した units 累計（推定） |
| `daily_limit` | int | 日次クォータ上限（10,000） |
| `last_call_cost` | int | 本リクエストで消費した units |
| `remaining_units_estimate` | int | `daily_limit - consumed_units_today`（負値はゼロにクランプ） |
| `reset_at_utc` | string | 次のリセット時刻 (UTC, RFC 3339) |
| `reset_at_jst` | string | 次のリセット時刻 (JST) |
| `reset_in_seconds` | int | 応答時点の現在 UTC とリセット時刻の差秒数 |

> リセットは **太平洋時間 (PT) 0:00**（YouTube Data API のクォータ仕様準拠）。DST は `zoneinfo` が自動処理。

---

### エラーコード

| error_code | HTTP (`/search`) | HTTP (`/summary`) | 意味 |
|---|---|---|---|
| `null` | 200 | 200 | エラーなし |
| `INVALID_URL` | — | 200 | YouTube URL として認識できない |
| `VIDEO_NOT_FOUND` | — | 200 | 動画が存在しない・非公開・削除済み |
| `TRANSCRIPT_NOT_FOUND` | — | 200 | 指定言語の字幕が見つからない |
| `TRANSCRIPT_DISABLED` | — | 200 | 字幕機能が無効化されている |
| `RATE_LIMITED` | 503 | 200 | YouTube 側のレート制限・5xx |
| `CLIENT_RATE_LIMITED` | 429 | 200 | 本 API のクライアント側レート制限超過 |
| `METADATA_FAILED` | — | 200 | メタデータ取得失敗（字幕は取得成功） |
| `INTERNAL_ERROR` | 500 | 200 | 予期せぬエラー |
| `QUOTA_EXCEEDED` | 429 | — | YouTube Data API 日次クォータ枯渇 |
| `UNAUTHORIZED` | 401 | (403) | `X-API-KEY` 不正・欠落（`/summary` は後方互換のため 403） |

---

## 必要条件

- Docker Engine 20.10 以降
- Docker Compose v2.0 以降
- Python 3.12（ローカル開発時のみ）
- YouTube Data API v3 の API キー（[Google Cloud Console](https://console.cloud.google.com/apis/credentials) で発行）
- Tailscale アカウント（ホスト側にインストール済みのクライアント）

## セットアップ手順

### 1. 環境変数の設定

```bash
cp .env.example .env

cat > .env.local << 'EOF'
API_KEY=your-secret-api-key-here
YOUTUBE_API_KEY=AIzaSyXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
EOF
```

| ファイル | 変数名 | 説明 | 必須 |
|---|---|---|---|
| `.env` | `LOG_LEVEL` | DEBUG / INFO / WARNING / ERROR | いいえ |
| `.env.local` | `API_KEY` | FastAPI 認証キー（X-API-KEY ヘッダーで送信） | はい |
| `.env.local` | `YOUTUBE_API_KEY` | YouTube Data API v3 のキー | はい |

### 2. Tailscale のセットアップ（ホスト側）

ホスト側（Windows 等）の Tailscale クライアントに依存します。サイドカーコンテナは使用しません。

1. ホスト OS に [Tailscale クライアント](https://tailscale.com/download) をインストール
2. ログインして Tailnet に参加

### 3. 起動

```bash
docker compose up -d
docker compose logs -f api
```

起動時に `quota_tracker を初期化しました（DB: data/usage/usage.db, consumed_units_today: …）` のログが出れば SQLite 復元 OK。

### 4. 動作確認

```bash
# ヘルスチェック
curl http://localhost:10000/

# /summary
curl -X POST http://localhost:10000/api/v1/summary \
  -H "Content-Type: application/json" -H "X-API-KEY: your-api-key" \
  -d '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}'

# /search
curl -X POST http://localhost:10000/api/v1/search \
  -H "Content-Type: application/json" -H "X-API-KEY: your-api-key" \
  -d '{"q": "FastAPI tutorial"}'
```

---

## 運用

### 本番

```bash
docker compose up -d        # 起動
docker compose down         # 停止
docker compose restart api  # 再起動
docker compose logs -f api  # ログ
docker compose build api    # 再ビルド
```

本番 `docker-compose.yml` は `data/usage/` を bind mount し、SQLite (`usage.db`) をホスト側に永続化します。コンテナ再起動・再ビルド後も `consumed_units_today` は復元されます。

### Staging（並走検証）

`compose.staging.yml` は本番 `:10000` を生かしたまま `:10001` で並走できる構成です。

```bash
docker compose -f compose.staging.yml up -d   # 起動 (port 10001)
docker compose -f compose.staging.yml down    # 停止
```

トップレベルに `name: youtube-api-staging` を持つので本番プロジェクト (`youtube_summary_api`) と分離されます。

### ローカル開発（Docker 外）

```bash
uvicorn main:app --host 0.0.0.0 --port 10000
```

---

## テスト

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

全 207 件、外部通信なし（すべてモック）。テストは Phase ごとに整理されています:

| ファイル | 件数 | 範囲 |
|---|---|---|
| `test_schemas.py` | 6 | 既存 `SummaryResponse` モデル |
| `test_search_schemas.py` | 50 | `SearchRequest` / `SearchResult` / `SearchResponse` / `Quota` |
| `test_async_rate_limiter.py` | 5 | `/search` のスライディングウィンドウ・レート制限 |
| `test_quota_tracker.py` | 10 | SQLite 永続化 + ContextVar 隔離 + PT 0:00 リセット |
| `test_search_service.py` | 31 | `/search` サービス層 (search/videos/channels) + 防御的型チェック |
| `test_search_endpoint.py` | 9 | `/search` ルーター統合 |
| `test_summary_quota_injection.py` | 5 | `/summary` への quota 注入 + 履歴記録 |
| `test_youtube_service.py` | 72 | 既存 `/summary` サービス層（回帰確認用） |
| `test_api_endpoint.py` | 9 | 既存 `/summary` ルーター（回帰確認用） |
| `test_rate_limiter.py` | 10 | 既存 `/summary` レート制限（回帰確認用） |

---

## ディレクトリ構造

```
.
├── app/
│   ├── core/
│   │   ├── constants.py            # エラーコード・メッセージ・APIエンドポイント等の定数（10種のエラーコード）
│   │   ├── logging_config.py       # ロギング設定
│   │   ├── rate_limiter.py         # /summary 用クライアント側レート制限（threading.Lock）
│   │   ├── async_rate_limiter.py   # /search 用クライアント側レート制限（asyncio.Lock + sliding window）
│   │   ├── quota_tracker.py        # YouTube Daily Quota 追跡（in-memory + SQLite + ContextVar）
│   │   └── security.py             # APIキー認証（/summary は 403、/search は 401）
│   ├── models/
│   │   └── schemas.py              # SummaryResponse / SearchRequest / SearchResponse / SearchResult / Quota
│   ├── routers/
│   │   ├── summary.py              # POST /api/v1/summary
│   │   └── search.py               # POST /api/v1/search
│   └── services/
│       ├── youtube.py              # /summary 用: YouTube Data API v3 + youtube-transcript-api
│       └── youtube_search.py       # /search 用: search.list → videos.list → channels.list
├── tests/                           # 207 件、全モック
├── data/
│   └── usage/
│       ├── .gitkeep
│       └── usage.db                # SQLite (WAL mode、bind mount で永続化、Git 管理外)
├── docker/
│   └── Dockerfile.api
├── docker-compose.yml              # 本番 (port 10000、SQLite bind mount あり)
├── docker-compose.override.yml     # 開発用プロファイル
├── compose.staging.yml             # 仮運用 (port 10001、本番並走可能)
├── main.py
├── requirements.txt
├── requirements-dev.txt
└── pytest.ini
```

---

## 技術スタック

| コンポーネント | 技術 |
|---|---|
| フレームワーク | FastAPI + Uvicorn |
| メタデータ取得 | YouTube Data API v3（主）/ oEmbed API（フォールバック） |
| 字幕取得 | youtube-transcript-api v1.2.x |
| ネットワーク | Tailscale（ホスト側、WireGuard 暗号化） |
| 認証 | API キー（X-API-KEY ヘッダー） |
| レート制限 (`/summary`) | プロセス内グローバル、最低 60 秒間隔 (`threading.Lock`) |
| レート制限 (`/search`) | スライディングウィンドウ 60 秒/10 リクエスト (`asyncio.Lock`) |
| クォータ追跡 | プロセス内 in-memory + SQLite (WAL mode) 永続化、PT 0:00 自動リセット |
| 履歴記録 | SQLite `api_calls` テーブル、認証通過後の全リクエストを 1 行記録 |

---

## セキュリティ

- `.env` / `.env.local` / `data/usage/usage.db` は `.gitignore` に含まれ、バージョン管理されません
- 本 API は公開せず、Tailnet 経由のアクセスのみを想定
- API キーの比較には `secrets.compare_digest` を使用（タイミング攻撃対策）
- `YOUTUBE_API_KEY` はログ・エラーレスポンスに出力されないことをテストで検証

## ライセンス

Private
