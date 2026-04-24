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

### US-4: 残りクォータをその場で知りたい

**As a** AI エージェント  
**I want** どのレスポンスにも「今日あとどれだけ検索できるか」の目安が含まれる  
**So that** クォータを消費し切る前に、検索の戦略（検索回数を絞る、キーワードを整理する）を調整できる

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

- `q` 以外はすべて任意
- `max_results` は **指定不可（サーバー側で 50 固定）**。理由: クォータコストは件数に関わらず 100 units で一定のため、最大件数を返して AI 側で絞り込ませる方が効率的
- `type` は **`video` 固定**（リクエストパラメータなし）
- 省略時のデフォルトは YouTube API のデフォルト値（`order` は `relevance`、`video_duration` は `any`）に従う
- 不正な値（例: `order` が列挙外）は 422 Unprocessable Entity

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
    "last_call_cost": 102
  }
}
```

#### 必ず除外するフィールド

- **`transcript` / `transcript_language` / `is_generated` は絶対に含めない**
  - 理由: 50 件分の字幕を取ると `youtube-transcript-api` が短時間に大量に叩かれて IP が BAN される
  - AI が文字起こしを必要とする場合は、`video_id` を使って既存の `POST /api/v1/summary` を別途呼び出す（そこで 60 秒間隔制限により安全に取得される）

### FR-4: レスポンス（エラー時）

#### レート制限（短期）

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

#### 日次クォータ枯渇

```json
{
  "success": false,
  "status": "error",
  "message": "YouTube Data API の日次クォータ(10000 units)を使い切りました。太平洋時間午前0時(JST 4/26 16:00)にリセットされます。",
  "error_code": "QUOTA_EXCEEDED",
  "query": "...",
  "results": null,
  "quota": {
    "consumed_units_today": 10000,
    "remaining_units_estimate": 0,
    "daily_limit": 10000,
    "reset_at_utc": "2026-04-26T07:00:00Z",
    "reset_at_jst": "2026-04-26T16:00:00+09:00",
    "last_call_cost": 0
  }
}
```

#### その他エラー

既存のエラーコード（`INVALID_URL` 等）は `/search` では該当しないが、`INTERNAL_ERROR` は共通。

### FR-5: エラーコード一覧（`/search` 用）

| error_code | 発生条件 | HTTP status |
|---|---|---|
| `null` | 成功 | 200 |
| `CLIENT_RATE_LIMITED` | 自サーバのレート制限超過（直近1分10回） | 200 |
| `QUOTA_EXCEEDED`（**新設**） | 内部カウンタが日次上限到達 or YouTube が 403 quotaExceeded を返した | 200 |
| `RATE_LIMITED` | YouTube 側の一時的制限（IP ブロック、短期スロットル） | 200 |
| `INTERNAL_ERROR` | 予期せぬエラー | 200 |

HTTP ステータスは既存 `/summary` と同じく **常に 200** を返し、`success` と `error_code` で判定する（iPhone ショートカット互換設計の踏襲）。

### FR-6: 既存 `/summary` レスポンスへの `quota` 追加

- 既存レスポンスに `quota` オブジェクトを追加（既存フィールドはすべて不変）
- 追加専用なので後方互換性に影響なし
- `quota.last_call_cost` は `/summary` では通常 2（videos.list 1 + channels.list 1）

### FR-7: クライアント側レート制限

#### `/search` — **新設**

- **方式**: スライディングウィンドウ（直近 60 秒間のリクエスト数を記録）
- **上限**: 直近 1 分で 10 回
- 上限超過時は `CLIENT_RATE_LIMITED` を返し、`retry_after` に「ウィンドウ先頭のリクエストが 60 秒経過するまでの秒数」を入れる
- エラーメッセージには **ルール本文（"1分あたり最大10回"）と retry_after 秒数** を必ず含める（AI の学習容易性）
- プロセス再起動でリセット（永続化しない）

#### `/summary` — **既存維持**

- プロセス内グローバル 60 秒間隔（`app/core/rate_limiter.py` の既存実装）
- 変更なし

#### 両者の関係

- `/search` と `/summary` は **独立したカウンタ**。互いに干渉しない
- 「/search を叩くと /summary が詰まる」ような UX は作らない

### FR-8: クォータ追跡とリセット

#### 追跡

- プロセス内 + **SQLite** に二重管理
  - プロセス内: 高速応答用の in-memory カウンタ
  - SQLite: 永続化と履歴（プロセス再起動後の復元に利用）
- 各 YouTube API 呼び出し後、`consumed_units_today` を加算
- 呼び出しのコストは以下で計上:
  - `search.list` → 100 units
  - `videos.list` → 1 unit（id バッチ 1 回あたり）
  - `channels.list` → 1 unit（id バッチ 1 回あたり）

#### リセット判定

- 太平洋時間（US/Pacific）の 0:00 を基準にリセット
  - PDT（夏時間 3〜11月頃）: UTC-7、JST との差 -16 時間（JST 16:00 にリセット）
  - PST（標準時）: UTC-8、JST との差 -17 時間（JST 17:00 にリセット）
- リクエスト毎に「前回記録時刻」と「現在時刻」を比較し、PT 0:00 を跨いでいたらカウンタを 0 にリセット
- リセット時刻は `zoneinfo.ZoneInfo("US/Pacific")` で計算（夏時間を自動処理）

#### 枯渇判定の保険

- 内部カウンタが 10,000 に達していなくても、YouTube が 403 `quotaExceeded` を返したら即 `QUOTA_EXCEEDED` に倒す
- プロセス再起動で SQLite から累計を復元できなかった場合の保険

### FR-9: 使用履歴の永続化

#### 保存場所

- **`data/usage/usage.db`**（SQLite）
- ホスト側からも読めるようにマウント、かつ **`.gitignore` 追加**

#### テーブル

- `api_calls` — 全 API 呼び出しの 1 行 1 レコード
  - `id`, `called_at_utc`, `endpoint` (`search` / `summary`), `input_summary`（q or video_id）
  - `units_cost`, `cumulative_units_today`
  - `http_success` (bool), `error_code` (nullable)
  - `transcript_success` (nullable、`/summary` のみ), `transcript_language` (nullable)
  - `result_count` (nullable、`/search` のみ)
- `quota_state` — 現在のクォータ状態（1 行）
  - `last_reset_at_utc`, `consumed_units_today`

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
└── test_search_service.py    # 新規
└── test_search_endpoint.py   # 新規
└── test_quota_tracker.py     # 新規
```

### 既存ファイルへの変更

- `app/core/constants.py`: `ERROR_QUOTA_EXCEEDED`、search 用レート制限定数、新メッセージを追加
- `app/models/schemas.py`: `SummaryResponse` に `quota` フィールドを追加（optional、既存テストは quota なしでも通るように）
- `app/routers/summary.py`: quota 集計を挟む
- `app/services/youtube.py`: videos.list / channels.list 呼び出し後に consumed_units を加算
- `main.py`: /search ルータを include
- `.gitignore`: `data/usage/` を追加

### テスト方針

- 既存の方針踏襲: 外部通信なし、すべてモック
- 新規テスト対象:
  - search サービス層（videos.list/channels.list バッチ、派生値計算、重複排除）
  - search エンドポイント統合（成功、レート制限、クォータ枯渇、バリデーションエラー）
  - quota_tracker 単体（リセット境界、PT 夏/冬時間切替、永続化と復元）
  - 既存 `/summary` テストの回帰（quota フィールド付与で壊れないこと）

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

1. ✅ `POST /api/v1/search` が存在し、X-API-KEY で認証される
2. ✅ `q` のみ指定で 50 件の結果が、すべての指定フィールド付きで返る
3. ✅ フィルタ（`order`, `published_after`, `video_duration`, `channel_id` 等）がすべて動作する
4. ✅ `transcript` 系フィールドは **絶対に含まれない**
5. ✅ `like_view_ratio` 等の派生値がサーバー側で計算されている
6. ✅ `quota` オブジェクトが /search と /summary の両レスポンスに含まれる
7. ✅ 直近 1 分に 11 回目を叩くと `CLIENT_RATE_LIMITED` が返り、`retry_after` と ルール本文がメッセージに含まれる
8. ✅ YouTube が 403 quotaExceeded を返す or 内部カウンタが 10,000 到達すると `QUOTA_EXCEEDED` が返り、`reset_at_utc` / `reset_at_jst` が正しい
9. ✅ PT 0:00 を跨ぐと内部カウンタが 0 にリセットされる（夏時間/冬時間どちらも正しく動く）
10. ✅ `data/usage/usage.db` に全呼び出しが記録されている（`api_calls` テーブル）
11. ✅ `data/usage/` が `.gitignore` 対象である
12. ✅ 既存の `/summary` のすべてのテスト（97 件）が quota 追加後も通る
13. ✅ 新規テストが追加され、外部通信なしで実行できる

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
