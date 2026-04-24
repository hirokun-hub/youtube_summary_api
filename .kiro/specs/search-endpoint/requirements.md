# ユーザーストーリー: YouTube 検索エンドポイント追加（信憑性評価付き）

## 概要

YouTube Summary API に新規エンドポイント `POST /api/v1/search` を追加し、キーワード検索結果に **各動画の信憑性評価・人気評価用メタデータ** を付与して返す。CLI 上の AI エージェントが情報収集ツールとして利用することを主目的とする。

既存の `POST /api/v1/summary` とその挙動はすべて維持する（破壊的変更なし、追加のみ）。

## 背景

### 現状のAPI

- `POST /api/v1/summary` が唯一のエンドポイント。URL を入力に、メタデータ+字幕を返す
- メタデータは YouTube Data API v3 (`videos.list` + `channels.list` = 約 2 units/回)
- 字幕は `youtube-transcript-api`
- クライアント側レート制限: プロセス内 60 秒間隔（文字起こしAPIのBAN予防）

### 追加の動機

1. AI エージェントが「ある話題について、信頼できる・人気のある動画を広く探す」ツールを必要としている
2. ID が既知の動画の詳細（/summary）は取れるが、**未知のトピックからの発見** ができない
3. 単に検索結果を返すだけでなく、**各動画の信憑性を AI が判断できる数値** を同時に返すことで、AI が主体的に絞り込める

### YouTube Data API v3 クォータ前提

- 無料プロジェクトの既定クォータ: **10,000 units / 日**
- リセット: **太平洋時間 午前0時（JST: 夏時間 16:00 / 冬時間 17:00）**
- `search.list` のコスト: **100 units / 回**（結果件数 1〜50 に関係なく一律）
- `videos.list` / `channels.list` は id バッチ呼び出しで 1 unit / 回（50 IDs まで）
- したがって 1 検索 = 約 **102 units**（search 100 + videos 1 + channels 1）→ 理論上最大 **~98 検索 / 日**

## 最重要方針: 既存機能の完全維持

**既存の `POST /api/v1/summary` が一切の変更なしで、現在とまったく同じデータを受け取れること。**

- 既存フィールド（`success`, `status`, `message`, `transcript` 等 22 項目）は名前・型・内容ともに変更なし
- 既存のエラーコード（`INVALID_URL` / `VIDEO_NOT_FOUND` / `TRANSCRIPT_NOT_FOUND` / `TRANSCRIPT_DISABLED` / `RATE_LIMITED` / `CLIENT_RATE_LIMITED` / `METADATA_FAILED` / `INTERNAL_ERROR`）の挙動は不変
- 既存のクライアント側レート制限（60 秒間隔）の挙動は不変
- **追加**: レスポンスに `quota` フィールドを付与（iPhone ショートカット側は未使用なので無視される）

## ユーザーストーリー

### US-1: 検索で動画を発見したい

**As a** CLI 上で動く AI エージェント  
**I want** キーワード（例: "ホリエモン AI 最新"）で YouTube 動画を検索して、最大 50 件の動画情報をまとめて取得できる  
**So that** 未知のトピックからでも「ID 一覧」「タイトル」「チャンネル」「再生数」を一度のリクエストで把握できる

### US-2: 各動画の信憑性を一目で判断したい

**As a** AI エージェント  
**I want** 各動画に「いいね率」「コメント率」「チャンネル登録者数」「チャンネル作成日」などの指標が付いている  
**So that** 単なる再生数ではなく、**エンゲージメント率** と **チャンネルの実績** の両面から、参照すべき動画を AI が自律的に選べる

### US-3: 検索条件を柔軟に指定したい

**As a** AI エージェント  
**I want** 並び順・投稿日範囲・動画の長さ・地域・言語・特定チャンネル内などでフィルタできる  
**So that** 「最新のニュースだけ」「長尺解説だけ」「このチャンネル内だけ」のように、タスクに応じた絞り込みができる

### US-4: 残りクォータと「リセットまでの時間」をその場で知りたい

**As a** AI エージェント  
**I want** どのレスポンスにも「今日あとどれだけ検索できるか」の目安と、**次のリセットまでの残り秒数**が含まれる  
**So that** 「残り units が少なくても、あと 20 分でリセットだから待てばよい」「まだ 6 時間あるから今は節約すべき」のように、時間軸も含めた戦略判断ができる（絶対時刻だけだと AI が現在時刻と差分計算する手間が発生するため、秒数で直接返す）

### US-5: クォータ枯渇時は「今日は諦めろ」と明示的に伝えたい

**As a** AI エージェント  
**I want** 1 日のクォータを使い切った時は、一時的なレート制限と区別された明確なエラーコードと次のリセット時刻が返る  
**So that** 「数秒待てば復活する」と誤認して無駄なリトライをせず、タスクを別アプローチに切り替えられる

### US-6: レート制限のルールをエラーメッセージから学習したい

**As a** AI エージェント  
**I want** レート制限で拒否された時、そのルール（"直近 1 分で 10 回まで" など）と `retry_after` 秒数がエラーメッセージ本文に含まれる  
**So that** 次回から呼び出し間隔を自己調整できる

### US-7: 利用履歴を後から分析したい

**As a** 開発者（個人運用者）  
**I want** 検索と要約の呼び出し履歴（クォータ消費、成功/失敗、transcript 取得率）がローカルに永続化される  
**So that** 「どのくらい使っているか」「文字起こし成功率はどうか」を後で SQL で集計できる

## 機能要件

### FR-1: 新規エンドポイント `POST /api/v1/search`

| 項目 | 内容 |
|---|---|
| メソッド | POST |
| パス | `/api/v1/search` |
| 認証 | 既存と同じ `X-API-KEY` ヘッダー |
| リクエスト Content-Type | `application/json` |

### FR-2: リクエストボディ

```json
{
  "q": "検索クエリ（必須）",
  "order": "relevance | date | rating | viewCount | title",
  "published_after": "2026-01-01T00:00:00Z",
  "published_before": "2026-04-25T23:59:59Z",
  "video_duration": "any | short | medium | long",
  "region_code": "JP",
  "relevance_language": "ja",
  "channel_id": "UCxxxx"
}
```

- `q` は必須、それ以外はすべて任意
- `max_results` は **指定不可（サーバー側で 50 固定）**。理由: クォータコストは件数に関わらず 100 units で一定のため、最大件数を返して AI 側で絞り込ませる方が効率的
- `type` は **`video` 固定**（リクエストパラメータなし。TC-6 参照）
- `videoEmbeddable` はデフォルト指定しない（埋め込み可能動画だけに偏るのを避ける。TC-6 参照）
- 省略時のデフォルトは YouTube API のデフォルト値（`order` は `relevance`、`video_duration` は `any`）に従う
- `safeSearch` / `regionCode` の既定値はサーバー側で設定しない（YouTube 側デフォルトに委ねる。専門家意見が分かれたため保留、実運用で再検討）
- 不正な値（例: `order` が列挙外、`q` 未指定、`published_after` の ISO 8601 不正）は **HTTP 422 Unprocessable Entity**（Pydantic 標準エラー形式）

### FR-3: レスポンス（成功時）

```json
{
  "success": true,
  "status": "ok",
  "message": "Successfully retrieved 50 results.",
  "error_code": null,
  "query": "ホリエモン AI 最新",
  "total_results_estimate": 48321,
  "returned_count": 50,
  "results": [
    {
      "video_id": "dQw4w9WgXcQ",
      "title": "動画タイトル",
      "channel_name": "チャンネル名",
      "channel_id": "UCxxxx",
      "upload_date": "2026-04-20",
      "thumbnail_url": "https://i.ytimg.com/vi/.../maxresdefault.jpg",
      "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
      "description": "概要欄の先頭...",
      "tags": ["AI", "ホリエモン"],
      "category": "News & Politics",
      "duration": 720,
      "duration_string": "12:00",
      "has_caption": true,
      "definition": "hd",

      "view_count": 120000,
      "like_count": 8400,
      "like_view_ratio": 0.07,
      "comment_count": 350,
      "comment_view_ratio": 0.0029,

      "channel_follower_count": 1520000,
      "channel_video_count": 842,
      "channel_total_view_count": 480000000,
      "channel_created_at": "2014-08-10",
      "channel_avg_views": 570000
    }
    // ... 最大 50 件
  ],
  "quota": {
    "consumed_units_today": 408,
    "remaining_units_estimate": 9592,
    "daily_limit": 10000,
    "reset_at_utc": "2026-04-26T07:00:00Z",
    "reset_at_jst": "2026-04-26T16:00:00+09:00",
    "reset_in_seconds": 32400,
    "last_call_cost": 102
  }
}
```

- `reset_in_seconds` はリクエスト応答時点の現在時刻（UTC）と次のリセット時刻（PT 0:00）の差を秒で返す。夏時間/冬時間の切り替えを跨ぐ日は `zoneinfo` の計算結果をそのまま用いる
- `remaining_units_estimate` は「概算」— YouTube の実クォータではなく本サーバーのローカルカウンタに基づく目安値
- `has_caption` は `videos.list(part=contentDetails).contentDetails.caption`（文字列 `"true"` / `"false"`）を bool 化した値。**追加 API コスト 0 units**（TC-8 参照）。AI が `/summary` に回すか判定する材料として使う
- 派生値（`like_view_ratio`, `comment_view_ratio`, `channel_avg_views`）はサーバー側で計算。分母が 0 の場合は `null`

#### 必ず除外するフィールド

- **`transcript` / `transcript_language` / `is_generated` は絶対に含めない**
  - 理由: 50 件分の字幕を取ると `youtube-transcript-api` が短時間に大量に叩かれて IP が BAN される
  - AI が文字起こしを必要とする場合は、`video_id` を使って既存の `POST /api/v1/summary` を別途呼び出す（そこで 60 秒間隔制限により安全に取得される）

### FR-4: レスポンス（エラー時）

`/search` は LLM Tool SDK との相性を優先して **標準 HTTP ステータスを返す**（既存 `/summary` は 200 固定を維持。詳細は TC-9 を参照）。レスポンスボディは成功時と同じ `success` / `error_code` / `message` / `quota` の形式を保つ（HTTP とボディの両方を見るクライアントに対応）。

#### 短期レート制限（`HTTP 429 Too Many Requests` + `Retry-After: 12`）

```json
{
  "success": false,
  "status": "error",
  "message": "検索レート制限: 直近1分で10回を超えました。ルール: 1分あたり最大10回。12秒後に再試行してください。",
  "error_code": "CLIENT_RATE_LIMITED",
  "query": "...",
  "results": null,
  "retry_after": 12,
  "quota": { ... }
}
```

#### 日次クォータ枯渇（`HTTP 429 Too Many Requests` + `Retry-After: 32400`）

```json
{
  "success": false,
  "status": "error",
  "message": "YouTube Data API の日次クォータ(10000 units)を使い切りました。あと 32400 秒(約 9 時間)でリセットされます(JST 4/26 16:00)。",
  "error_code": "QUOTA_EXCEEDED",
  "query": "...",
  "results": null,
  "quota": {
    "consumed_units_today": 10000,
    "remaining_units_estimate": 0,
    "daily_limit": 10000,
    "reset_at_utc": "2026-04-26T07:00:00Z",
    "reset_at_jst": "2026-04-26T16:00:00+09:00",
    "reset_in_seconds": 32400,
    "last_call_cost": 0
  }
}
```

#### 認証エラー（`HTTP 401 Unauthorized`）

```json
{
  "success": false,
  "status": "error",
  "message": "X-API-KEY ヘッダが不正または未設定です。",
  "error_code": "UNAUTHORIZED",
  "query": null,
  "results": null,
  "quota": null
}
```

#### リクエスト構造違反（`HTTP 422 Unprocessable Entity`）

FastAPI / Pydantic の標準バリデーションエラー形式（`detail[]` 配列）を返す。`q` 未指定、`order` が列挙外、`published_after` が ISO 8601 不正などが該当。

#### YouTube 側の一時制限（`HTTP 503 Service Unavailable` + `Retry-After`）

IP ブロック・短期スロットルなど。`RATE_LIMITED` エラーコードで返す。

#### 内部エラー（`HTTP 500 Internal Server Error`）

予期せぬ例外。`INTERNAL_ERROR` エラーコードで返す。

### FR-5: エラーコード・HTTP ステータス対応表（`/search` 用）

| error_code | 発生条件 | HTTP status | 追加ヘッダ |
|---|---|---|---|
| `null` | 成功 | 200 | — |
| `UNAUTHORIZED` | `X-API-KEY` ヘッダが不正または未設定 | 401 | — |
| （Pydantic 標準） | リクエストボディのスキーマ違反 | 422 | — |
| `CLIENT_RATE_LIMITED` | 自サーバのレート制限超過（直近1分10回） | 429 | `Retry-After: <秒数>` |
| `QUOTA_EXCEEDED`（**新設**） | 内部カウンタが日次上限到達 or YouTube が 403 quotaExceeded を返した | 429 | `Retry-After: <秒数>` |
| `RATE_LIMITED` | YouTube 側の一時的制限（IP ブロック、短期スロットル） | 503 | `Retry-After: <秒数>`（入手可能な場合） |
| `INTERNAL_ERROR` | 予期せぬエラー | 500 | — |

**`/summary` は従来どおり HTTP 200 固定**（iPhone ショートカット互換）。`/search` のみ標準 HTTP ステータスに切り替える。変更根拠は TC-9 および `docs/expert-reviews/2026-04-25-search-endpoint-design-review.md` を参照。

### FR-6: 既存 `/summary` レスポンスへの `quota` 追加

- 既存レスポンスに `quota` オブジェクトを追加（既存フィールドはすべて不変）
- 追加専用なので後方互換性に影響なし
- `quota.last_call_cost` は `/summary` では通常 2（videos.list 1 + channels.list 1）

### FR-7: クライアント側レート制限

#### `/search` — **新設**

- **方式**: スライディングウィンドウ（直近 60 秒間のリクエスト数を `collections.deque` で保持）
- **上限**: 直近 1 分で 10 回
- **排他制御**: `asyncio.Lock`（`threading.Lock` は使わない。理由は TC-4 参照）
- 上限超過時:
  - HTTP **429** を返す
  - `Retry-After: <秒数>` ヘッダを付与（「ウィンドウ先頭のリクエストが 60 秒経過するまでの秒数」、最低1）
  - レスポンスボディにも `retry_after` フィールドで同値を返す
  - `error_code = CLIENT_RATE_LIMITED`
- エラーメッセージには **ルール本文（"1分あたり最大10回"）と retry_after 秒数** を必ず含める（AI の学習容易性）
- プロセス再起動でリセット（永続化しない。将来 worker 2+ に増設する場合は SQLite か Redis ベースに移行が必要）

#### `/summary` — **既存維持**

- プロセス内グローバル 60 秒間隔（`app/core/rate_limiter.py` の既存実装）
- 変更なし（`threading.Lock` 利用は実害低く、本 PR のスコープ外）

#### 両者の関係

- `/search` と `/summary` は **独立したカウンタ**。互いに干渉しない
- 「/search を叩くと /summary が詰まる」ような UX は作らない

### FR-8: クォータ追跡とリセット

#### 二層構造（推定値 / 権威値）

| レイヤ | 役割 | 実装 |
|---|---|---|
| 推定（estimate） | プロセス内 in-memory カウンタ + SQLite 永続化 | レスポンスで `remaining_units_estimate` として返す |
| 権威（authoritative） | YouTube の 403 `quotaExceeded` を受信した瞬間に確定 | 内部カウンタに関係なく即 `QUOTA_EXCEEDED` に倒す |

YouTube の実消費量をリアルタイムに取得する公式 API は存在しない（GCP Cloud Quotas API は設定値のみ）。したがって **推定値で予防、403 で確定** の二層が唯一の現実解（TC-2 参照）。

#### 呼び出しコストの計上

- `search.list` → 100 units
- `videos.list` → 1 unit（id バッチ 1 回あたり、最大50 IDs）
- `channels.list` → 1 unit（id バッチ 1 回あたり、最大50 IDs）

#### リセット判定

- 基準: 太平洋時間 0:00
- タイムゾーン識別子: **`zoneinfo.ZoneInfo("America/Los_Angeles")`**（IANA 正式名、`US/Pacific` はエイリアスのため非推奨。TC-5 参照）
- DST 自動処理:
  - PDT（UTC-7）: JST 16:00 にリセット
  - PST（UTC-8）: JST 17:00 にリセット
- 算出式（UTC 保持・PT 変換は表示時のみ）:
  ```python
  now_pt = now_utc.astimezone(PT)
  next_midnight_pt = datetime.combine(
      now_pt.date() + timedelta(days=1), time.min, tzinfo=PT
  )
  reset_at_utc = next_midnight_pt.astimezone(timezone.utc)
  ```
- リクエスト毎に「前回記録時刻」と「現在時刻」を比較し、PT 0:00 を跨いでいたら内部カウンタを 0 にリセット

#### プロセス起動時の再計算

- SQLite から `SELECT SUM(units_cost) FROM api_calls WHERE called_at_utc >= (今日のPT0時をUTC換算した値)` で集計
- プロセス内カウンタに反映（手動でDBを触った場合の不整合も検出可能）

### FR-9: 使用履歴の永続化

#### 保存場所

- **`data/usage/usage.db`**（SQLite）
- ホスト側からも読めるようにマウント、かつ **`.gitignore` 追加**

#### 接続設定（全接続共通、TC-3 参照）

以下の PRAGMA を接続直後に必ず実行する:

- `PRAGMA journal_mode=WAL` — 読み書きの並行性確保
- `PRAGMA synchronous=NORMAL` — WAL 下で安全な fsync 頻度
- `PRAGMA busy_timeout=5000` — ロック待ち最大5秒
- `PRAGMA foreign_keys=ON` — 外部キー制約有効化

書き込みトランザクションは **`BEGIN IMMEDIATE`** で開始して書き込みロックを先取りする（暗黙の `BEGIN` だと `SQLITE_BUSY` を後から食う）。

async エンドポイントから同期 `sqlite3` を呼ぶ場合は `asyncio.to_thread()` 経由でスレッドプールに逃がす。

#### テーブル

- `api_calls` — 全 API 呼び出しの 1 行 1 レコード
  - `id`, `called_at_utc`, `endpoint` (`search` / `summary`), `input_summary`（q or video_id）
  - `units_cost`, `cumulative_units_today`
  - `http_status` (int), `http_success` (bool), `error_code` (nullable)
  - `transcript_success` (nullable、`/summary` のみ), `transcript_language` (nullable)
  - `result_count` (nullable、`/search` のみ)
- `quota_state` — 現在のクォータ状態（1 行、`CHECK (id = 1)` で単一行制約）
  - `id`, `quota_date_pt`, `consumed_units_today`, `daily_limit`, `updated_at_utc`

#### 後処理

- ローテーションは当面不要（SQLite 1 ファイル、個人利用で十分小さい）
- 90 日分を目安に、必要になったら DELETE で整理

### FR-10: YouTube API 呼び出しの内部フロー

1. `search.list(q, type=video, maxResults=50, [filters])` を呼ぶ（100 units）
2. 返ってきた `items[].id.videoId` を重複排除して最大 50 IDs
3. `videos.list(id=<ids>, part=snippet,contentDetails,statistics)` を 1 回呼ぶ（1 unit）
4. `items[].snippet.channelId` を重複排除して最大 50 unique channel IDs
5. `channels.list(id=<ids>, part=snippet,statistics)` を 1 回呼ぶ（1 unit）
6. 3 つのレスポンスを結合して `results[]` を組み立て
7. 派生値（`like_view_ratio`, `comment_view_ratio`, `channel_avg_views`）を計算
8. `quota` フィールドを付与して返す

## 技術方針

### 新規依存

- 追加ライブラリなし（既存の `requests` で YouTube Data API v3 を呼べる）
- Python 標準の `sqlite3` と `zoneinfo`（Python 3.9+）を利用

### 環境変数

- 既存の `YOUTUBE_API_KEY` を流用（.env.local）
- 新規: なし

### ディレクトリ・ファイル追加予定

```
app/
├── core/
│   ├── quota_tracker.py      # 新規: クォータカウンタ + SQLite 永続化
│   └── search_rate_limiter.py # 新規 or 既存 rate_limiter.py に統合検討
├── models/
│   └── schemas.py            # SearchRequest / SearchResponse / SearchResult / Quota モデル追加
├── routers/
│   └── search.py             # 新規: POST /api/v1/search
└── services/
    └── youtube_search.py     # 新規: search.list + videos.list + channels.list
data/
└── usage/
    └── usage.db              # SQLite（.gitignore）
tests/
├── test_search_service.py    # 新規
├── test_search_endpoint.py   # 新規
├── test_quota_tracker.py     # 新規
├── test_async_rate_limiter.py # 新規: asyncio.Lock + sliding window
├── snapshots/                # 新規: 実 API レスポンスのスキーマスナップショット
│   ├── search_list_sample.json
│   ├── videos_list_sample.json
│   └── channels_list_sample.json
└── live/                     # 新規: 実 API 統合テスト (RUN_LIVE_YOUTUBE_TESTS=1 で有効化)
    └── test_youtube_search_live.py
```

### 既存ファイルへの変更

- `app/core/constants.py`: `ERROR_QUOTA_EXCEEDED`、search 用レート制限定数、新メッセージを追加
- `app/models/schemas.py`: `SummaryResponse` に `quota` フィールドを追加（optional、既存テストは quota なしでも通るように）
- `app/routers/summary.py`: quota 集計を挟む
- `app/services/youtube.py`: videos.list / channels.list 呼び出し後に consumed_units を加算
- `main.py`: /search ルータを include
- `.gitignore`: `data/usage/` を追加

### テスト方針（3層構成、TC-12 参照）

#### 第1層: 通常 CI、全モック

- 既存97件 + 新規テストを追加
- `requests.get` を `unittest.mock` でパッチ、外部通信なし
- テスト対象:
  - search サービス層（videos.list/channels.list バッチ、派生値計算、重複排除、`itertools.batched` 分割）
  - search エンドポイント統合（成功、401、422、429×2種、500、503）
  - quota_tracker 単体（PT 0:00 リセット境界、DST 開始・終了、再起動後の SQLite 復元）
  - async レート制限（`asyncio.Lock` のスレッドセーフ性、`Retry-After` ヘッダ付与）
  - 既存 `/summary` テストの回帰（quota フィールド付与で壊れないこと）

#### 第2層: スキーマスナップショット検証

- 実 API レスポンスを 1 回保存 → `tests/snapshots/{search,videos,channels}_list_sample.json`
- Pydantic モデルで `model_validate(json.load(f))` が通ることを検証
- YouTube 側のスキーマ変更を検知する仕組み

#### 第3層: 実 API 統合テスト（任意）

- 環境変数 `RUN_LIVE_YOUTUBE_TESTS=1` で有効化（通常 CI からは除外）
- 週次または月次で 1 回のみ実行（約 102 units = 日次の 1%）
- `search.list` → `videos.list` → `channels.list` の 1 フローをライブで叩き、Pydantic 検証を通す

## 技術的制約

本セクションは 2026-04-25 に実施した専門家3名（O / A / G）によるレビューで信頼度 97% 以上のコンセンサスが得られた技術的決定事項を列挙する。詳細な根拠・コード例・参考リンクは `docs/expert-reviews/2026-04-25-search-endpoint-design-review.md` を参照。

### TC-1: HTTP クライアント

- `requests.Session` + `urllib3.util.retry.Retry` を使用
- リトライ対象: 429 / 500 / 502 / 503 / 504、`backoff_factor=1.0`、`backoff_jitter=0.3`
- `Retry-After` ヘッダを尊重 (`respect_retry_after_header=True`)
- **403 `quotaExceeded` はリトライしない**（`errors[0].reason` で判別し即時 `QUOTA_EXCEEDED` 判定）
- `google-api-python-client` は採用しない（依存 50MB+、YouTube Data API 向け自動リトライ未実装のため）

### TC-2: クォータ追跡の二層構造

- **推定値**: プロセス内カウンタ + SQLite 永続化 →  `remaining_units_estimate` として返す
- **権威値**: YouTube の 403 `quotaExceeded` を受けたら即 `QUOTA_EXCEEDED`（内部カウンタに関係なく）
- プロセス起動時は `SELECT SUM(units_cost) FROM api_calls WHERE called_at_utc >= 今日のPT0時UTC` で `quota_state` を再計算・検証

### TC-3: SQLite 並行耐性

- 接続初期化で以下の PRAGMA を実行:
  - `PRAGMA journal_mode=WAL`
  - `PRAGMA synchronous=NORMAL`
  - `PRAGMA busy_timeout=5000`
  - `PRAGMA foreign_keys=ON`
- 書き込みは `BEGIN IMMEDIATE` で書き込みロックを先取り（暗黙の `BEGIN` は使わない）
- async エンドポイントから同期 `sqlite3` を呼ぶ時は `asyncio.to_thread()` 経由
- PostgreSQL 移行閾値: 持続書き込み 10 QPS / 同時 writer 3+ / 同時接続 20+ / `SQLITE_BUSY` 週1回以上（いずれも本件の現状規模では該当しない）

### TC-4: 非同期コンテキストのロック

- `/search` のレート制限は **`asyncio.Lock`** を使用（`threading.Lock` を async def 内で使わない）
- `collections.deque` + `asyncio.Lock` で自前スライディングウィンドウ実装
- 将来 worker 2+ 化時は in-memory ロックが worker ごとに分裂するため、SQLite / Redis ベースへの移行を検討

### TC-5: タイムゾーン処理

- `zoneinfo.ZoneInfo("America/Los_Angeles")` を使用（IANA 正式名。`US/Pacific` は非推奨のエイリアス）
- リセット時刻は `datetime.combine(now_pt.date() + timedelta(days=1), time.min, tzinfo=PT).astimezone(timezone.utc)` で算出
- 内部処理は常に UTC で保持、PT への変換は表示時のみ
- DST 境界テストを必ず含める: 2026-03-08 開始・2026-11-01 終了、PT 0:00 の前後±1分、`fold` 属性を伴う曖昧時刻

### TC-6: search.list のパラメタ

- **サーバー側で固定**: `type=video`, `maxResults=50`
- **既定で指定しない**: `videoEmbeddable`（埋め込み可能動画のみに偏るため）
- **リクエストで受け付ける**: `order`, `publishedAfter`, `publishedBefore`, `videoDuration`, `regionCode`, `relevanceLanguage`, `channelId`
- `safeSearch` / `regionCode` の既定値は保留（YouTube 側デフォルトに委ねる）

### TC-7: バッチ呼び出し

- `videos.list` / `channels.list` は 50 IDs までカンマ区切り → **1 unit / コール**
- `part=` に複数指定（`snippet,contentDetails,statistics`）してもコストは 1 unit（個別コール分割より割安）
- 50件超の分割は Python 3.12 標準の `itertools.batched(ids, 50)` を使用

### TC-8: `has_caption` フィールド

- `videos.list(part=contentDetails)` の `contentDetails.caption`（文字列 `"true"` / `"false"`）を bool 化して `has_caption` で返す
- 追加 API コスト **0 units**（既存の videos.list に含まれる）
- AI が「字幕ある動画だけ `/summary` に回そう」と判断可能に
- transcript 本文は絶対に含めない方針は変わらず（`/search` での50本一括字幕取得は IP BAN リスクのため）

### TC-9: HTTP ステータスコード方針（**設計変更**）

- **`/summary` は 200 固定を維持**（iPhone ショートカット互換）
- **`/search` は標準 HTTP ステータスを返す**（既存 requirements.md の「常に 200」方針を上書き）

| 状況 | HTTP | error_code |
|---|---|---|
| 成功 | 200 | `null` |
| 認証エラー | 401 | `UNAUTHORIZED` |
| リクエスト構造違反 | 422 | （Pydantic/FastAPI 標準） |
| 自サーバ短期レート制限 | 429 | `CLIENT_RATE_LIMITED` |
| YouTube 日次クォータ枯渇 | 429 または 403 | `QUOTA_EXCEEDED` |
| YouTube 一時制限 | 503 または 429 | `RATE_LIMITED` |
| 内部エラー | 500 | `INTERNAL_ERROR` |

- 429 / 503 / 403 には **`Retry-After` ヘッダ** を付与
- レスポンスボディは既存形式（`success`, `error_code`, `message`, `quota`）を維持（HTTP・ボディ両対応）
- 変更理由: LLM Tool SDK（Anthropic / OpenAI / MCP）は HTTP ステータスで自動リトライを分岐するため、200 固定ではエラーを成功と誤認しハルシネーションする

### TC-10: Pydantic v2 スキーマ

- 型ヒントは **`X | None`** で統一（`Optional[X]` は新規コードで使わない）
- `@computed_field` を使って `remaining_units_estimate` / `reset_in_seconds` を動的計算
- 全レスポンスモデルに `model_config = ConfigDict(frozen=True, extra="forbid")` を適用
- `RootModel` は使わない（`results` はフィールド）
- `@model_validator(mode="after")` で `success` と `error_code` の相関制約を追加

### TC-11: 観測性

| 項目 | 判定 |
|---|---|
| Python 標準 `logging` | 必須 |
| SQLite `api_calls` テーブル | 必須 |
| JSON 構造化ログ | 推奨 |
| `X-Request-ID` ヘッダ | あったら便利 |
| Sentry / Prometheus / OpenTelemetry | 過剰（本件規模では不要） |

### TC-12: テスト戦略

- **第1層**: 全モックで既存97件 + 新規テスト（通常 CI で毎回実行）
- **第2層**: 実 API レスポンス JSON を保存したスナップショットに対する Pydantic スキーマ検証（API 仕様変更の検知）
- **第3層**: 実 API を週次または月次で 1 回だけ叩く統合テスト（環境変数 `RUN_LIVE_YOUTUBE_TESTS=1` で有効化、約 102 units = 日次 1%）
- Pact 等の本格契約テストは採用しない

---

## 非機能要件

### NFR-1: パフォーマンス

- 1 検索リクエストで YouTube API を **最大 3 回**（search/videos/channels）しか叩かない
- videos.list と channels.list はバッチ 50 IDs/回で 1 unit に抑える

### NFR-2: セキュリティ

- `YOUTUBE_API_KEY` をログ・エラーレスポンスに含めない（既存方針踏襲、専用テスト追加）
- `.env.local` / `data/usage/` は `.gitignore` 徹底

### NFR-3: 可観測性

- ログ: `/search` の呼び出し時にクエリ、件数、units_cost、remaining をログ出力（既存 logging に合わせた日本語）
- SQLite に全呼び出しを記録（後述）

### NFR-4: 後方互換性

- 既存の `/summary` クライアント（iPhone ショートカット）は無修正で動くこと
- レスポンスへの `quota` 追加は JSON の上書きでなく新規キー追加のみ

## 受け入れ基準

1. ✅ `POST /api/v1/search` が存在し、`X-API-KEY` で認証される（不正時は HTTP 401 + `error_code=UNAUTHORIZED`）
2. ✅ `q` のみ指定で 50 件の結果が、すべての指定フィールド付きで返る（HTTP 200）
3. ✅ リクエストボディのスキーマ違反（`q` 未指定、`order` 列挙外など）で HTTP 422 が返る
4. ✅ フィルタ（`order`, `published_after`, `video_duration`, `channel_id` 等）がすべて動作する
5. ✅ 各結果に `has_caption` が含まれる（`contentDetails.caption` 由来、追加コスト 0 units）
6. ✅ `transcript` / `transcript_language` / `is_generated` フィールドは **絶対に含まれない**
7. ✅ `like_view_ratio` 等の派生値がサーバー側で計算されている（分母 0 時は null）
8. ✅ `quota` オブジェクトが /search と /summary の両レスポンスに含まれる（`remaining_units_estimate`, `reset_in_seconds` 含む）
9. ✅ 直近 1 分に 11 回目を叩くと **HTTP 429** + `Retry-After: <秒数>` ヘッダ + `error_code=CLIENT_RATE_LIMITED` が返り、ルール本文と `retry_after` 秒数がメッセージに含まれる
10. ✅ YouTube が 403 quotaExceeded を返す or 内部カウンタが 10,000 到達すると **HTTP 429** + `Retry-After` + `error_code=QUOTA_EXCEEDED` が返る。`reset_at_utc` / `reset_at_jst` / `reset_in_seconds` が正しい（`reset_in_seconds` は応答時点の現在 UTC と reset_at_utc の差と一致）
11. ✅ PT 0:00 を跨ぐと内部カウンタが 0 にリセットされる（2026-03-08 DST 開始 / 2026-11-01 DST 終了の両テストが通る）
12. ✅ `asyncio.Lock` がスライディングウィンドウ実装で使われている（`threading.Lock` 不使用）
13. ✅ SQLite 接続で `journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=5000`, `foreign_keys=ON` が適用されている
14. ✅ プロセス再起動後、SQLite の `api_calls` から `consumed_units_today` が再計算される
15. ✅ `data/usage/usage.db` に全呼び出しが記録されている（`api_calls` テーブル）
16. ✅ `data/usage/` が `.gitignore` 対象である
17. ✅ 既存の `/summary` のすべてのテスト（97 件）が quota 追加後も通る（HTTP 200 固定が維持されている）
18. ✅ 新規テスト（サービス層・エンドポイント・quota_tracker・async レート制限）が追加され、全モックで実行できる
19. ✅ スキーマスナップショットテスト（`tests/snapshots/*.json`）が追加されている
20. ✅ 実 API 統合テストが `RUN_LIVE_YOUTUBE_TESTS=1` で有効化できる形で追加されている

## スコープ外（このPRでやらないこと）

- YouTube Data API v3 の別メソッド（`playlists.list`, `channels.list` 単独検索など）のエンドポイント化
- 検索結果のキャッシュ（同一クエリの再検索で API を叩かない、など）
- 複数ユーザー別のクォータ管理（現状は個人利用のため単一バケット）
- GCP Cloud Quotas API を使った実残量取得
- 要約エンドポイント化の再設計（`/search` と `/summary` の統合は行わない）

## 参考

- [YouTube Data API v3 Quota Costs](https://developers.google.com/youtube/v3/determine_quota_cost)
- [search.list reference](https://developers.google.com/youtube/v3/docs/search/list)
- [videos.list reference](https://developers.google.com/youtube/v3/docs/videos/list)
- [channels.list reference](https://developers.google.com/youtube/v3/docs/channels/list)
