# 要件定義書: チャンネル動画一覧エンドポイント (channel-videos-endpoint)

## 1. 概要

YouTube Summary API に新規エンドポイント `POST /api/v1/channel_videos` を追加する。指定されたチャンネルの最新アップロード動画 50 件を、低コスト（3〜4 quota units）かつ既存 `/search` と同形の信憑性指標付きで返す。`/search` の **34 倍効率** で「特定チャンネルの最新動画一覧」を取得できる用途別最適化エンドポイントとする。

## 2. 背景

### 2.1 既存 `/search` の限界

`/search` は YouTube `search.list` (100u) を経由するため、特定チャンネル内の動画一覧を取りたいだけのシンプルな用途でも **常に 102 units** を消費する。たとえば LLM エージェントが「@MrBeast の最新動画見せて」というユーザー指示を実行する場合、関連度ランキングは不要で、単純にアップロード日時順の最新 50 件が欲しいだけの状況が大半である。

### 2.2 YouTube 公式 API の最安経路

YouTube Data API v3 は以下の組み合わせで「チャンネルの uploads プレイリスト経由の動画一覧取得」を **合計 3 units** で提供している:

```
channels.list?id=<channel_id>&part=snippet,contentDetails,statistics  (1u)
  └ contentDetails.relatedPlaylists.uploads にチャンネル uploads プレイリスト ID
playlistItems.list?playlistId=<uploads>&part=contentDetails             (1u)
  └ 最新 50 件の videoId
videos.list?id=<csv>&part=snippet,contentDetails,statistics             (1u)
  └ 動画詳細 (既存 /search と同じフィールド)
```

handle (`@MrBeast` 等) が入力の場合は `channels.list?forHandle` を 1u 追加で挟む（合計 4u）。本エンドポイントはこの YouTube 公式 API 経路を直接ラップする。

### 2.3 想定利用者

LLM エージェント / iPhone Shortcut / 内部スクリプト。すべて Tailnet 経由の単一ユーザー利用を前提。

## 3. 最重要方針: 既存機能の後方互換維持

- `POST /api/v1/summary` の挙動は変更しない（HTTP 200 固定、22 既存フィールド + `quota` のレスポンス形式は不変）
- `POST /api/v1/search` の挙動は変更しない（リクエスト・レスポンス・エラーコード・HTTP マッピングすべて不変）
- 既存テスト 207 件すべてが PASS する状態を維持する
- 既存共通インフラ (`quota_tracker` / `async_rate_limiter` / `SearchHTTPException` / `record_api_call` / `Quota` モデル / `SearchResult` モデル) を再利用し、新規追加は `/channel_videos` 固有の最小コードに留める

---

## 4. ユーザーストーリー

### US-1: channel_id を知っている場合に最安で動画一覧を取得したい

**ストーリー**: 内部スクリプトまたは LLM エージェントとして、すでに channel_id (`UCxxx`) が手元にあるとき、解決ステップを省いて 3u の最安コストで最新動画 50 件を取得したい。なぜなら、channel_id は前回の `/search` レスポンスや永続キャッシュから取得済みのケースが多く、handle 解決をやり直すのは無駄だから。

**要件 (EARS)**:
- When クライアントが `POST /api/v1/channel_videos` のリクエストボディに `channel` フィールドとして `^UC[A-Za-z0-9_-]{22}$` にマッチする値を送信したとき、システムはその値を YouTube channel_id として直接使用する
- The system shall channels.list (1u) + playlistItems.list (1u) + videos.list (1u) の合計 3 quota units でレスポンスを構築する
- When 該当チャンネルが存在し動画も存在するとき、the system shall HTTP 200 で `success=true` の `ChannelVideosResponse` を返す
- The system shall 各動画について `/search` の `SearchResult` と同一構造の 25 フィールドを `results` 配列に格納する

### US-2: handle (`@MrBeast` 等) を知っている場合にも動画一覧を取得したい

**ストーリー**: ユーザーから `@MrBeast` のような handle を渡された LLM として、内部で channel_id への解決を任せて動画一覧を返したい。なぜなら、handle 解決のために別エンドポイント呼び出しを挟むのは LLM のツール使用ロジックを複雑にするから。

**要件 (EARS)**:
- When 入力 `channel` フィールドの値が `^UC[A-Za-z0-9_-]{22}$` にマッチしないとき、the system shall その値を handle として扱う
- The system shall handle 値の先頭 `@` を内部的に除去してから `channels.list?forHandle` に渡す（YouTube は @ あり/なし両方を受け付けるが正規化のため）
- When `channels.list?forHandle` が 1 件以上の channel item を返したとき、the system shall その先頭の channel_id で US-1 と同等のフローを継続する
- If `channels.list?forHandle` が空 `items` 配列を返したとき、then the system shall HTTP 404 + `error_code=CHANNEL_NOT_FOUND` を返す
- The system shall handle 解決込みで合計 4 quota units を消費する

### US-3: 50 件以上の動画にページングでアクセスしたい

**ストーリー**: チャンネルの全動画を集計したい LLM として、50 件を超える動画を順次取得したい。なぜなら、チャンネル傾向分析や時系列調査では 50 件では足りないから。

**要件 (EARS)**:
- When YouTube `playlistItems.list` のレスポンスに `nextPageToken` が含まれるとき、the system shall それをそのまま `next_page_token` フィールドとしてレスポンスに含める
- When `nextPageToken` が含まれないとき、the system shall `next_page_token: null` を返す
- When クライアントがリクエストボディに `page_token` を指定したとき、the system shall その値を YouTube `playlistItems.list?pageToken=...` に渡す
- While `page_token` が指定されているとき、the system shall `channels.list` を呼ばず、`playlistItems.list` (1u) + `videos.list` (1u) の合計 2 quota units で完結する
- The system shall `channels` トップレベルブロックは初回ページと同じスキーマを保つが、`page_token` 指定時は値を null にしても良い（実装簡素化のため）

### US-4: 動画ごとの信憑性指標を取得したい

**ストーリー**: LLM として `/search` と一貫した信憑性指標で各動画を評価したい。なぜなら、`/search` と `/channel_videos` で動画スコアリングロジックを共通化したいから。

**要件 (EARS)**:
- The system shall 各動画オブジェクトに `view_count`, `like_count`, `comment_count`, `like_view_ratio`, `comment_view_ratio` を含める
- The system shall `like_view_ratio` を `like_count / view_count` で計算し、`view_count` が 0 または null のときは null を返す
- The system shall `comment_view_ratio` も同様に計算する
- The system shall `has_caption` を YouTube `contentDetails.caption` の文字列 "true" / "false" を Python bool に変換した値で返す
- The system shall `transcript` / `transcript_language` / `is_generated` フィールドは結果に **絶対に含めない**（最大 50 件取得時のクォータ消費を抑える設計上の意図）

### US-5: チャンネル全体の情報を 1 リクエストで把握したい

**ストーリー**: LLM として、動画一覧と一緒にチャンネル自体のメタ情報（登録者数、累計再生数、開設日等）も把握したい。なぜなら、チャンネル評価には個別動画の指標と全体指標の両方が必要だから。

**要件 (EARS)**:
- The system shall 初回ページのレスポンスのトップレベルに `channel` オブジェクトを含める
- The system shall `channel` オブジェクトに `channel_id`, `channel_name`, `channel_follower_count`, `channel_video_count`, `channel_total_view_count`, `channel_created_at`, `channel_avg_views` の 7 フィールドを含める
- The system shall `channel_avg_views` を `channel_total_view_count / channel_video_count` で計算し、分母が 0 または null のときは null とする
- Where `subscriberCount` が hidden（YouTube が `hiddenSubscriberCount: true` を返す）のとき、the system shall `channel_follower_count` を null とする

### US-6: クォータ消費を可視化したい

**ストーリー**: API クライアントとして、リクエストごとの消費 units と本日の累積・残量・リセット時刻を確認したい。なぜなら、quota 残量を超過させずに API 利用計画を立てたいから。

**要件 (EARS)**:
- The system shall 認証通過後の全レスポンス（200 / 429 / 503 / 500 / 404）に `quota` オブジェクトを含める
- The system shall `quota.last_call_cost` に本リクエストで消費した units（3, 4, 2 のいずれか）を入れる
- The system shall `quota.consumed_units_today` に既存 `quota_tracker` の in-memory + SQLite 復元値を入れる
- The system shall `quota.reset_in_seconds` を応答時点の現在 UTC と次の PT 0:00 の差秒数で返す
- The system shall `quota` オブジェクトのフィールド構造は既存 `Quota` モデル（`/search` / `/summary` で使用中）と完全同一とする

### US-7: 認証エラーを明確に判別したい

**ストーリー**: API クライアントとして、認証エラーを 401 で受け取り、再認証フローを開始したい。なぜなら、`/summary` の 403 と区別したい LLM エージェントが多いから（既存 `/search` でも同じ方針）。

**要件 (EARS)**:
- If `X-API-KEY` ヘッダーが欠落しているとき、then the system shall HTTP 401 + `error_code=UNAUTHORIZED` を返す
- If `X-API-KEY` ヘッダーの値が環境変数 `API_KEY` と一致しないとき、then the system shall HTTP 401 + `error_code=UNAUTHORIZED` を返す
- The system shall 401 レスポンスには `quota` フィールドを **含めない**（認証通過前のため）
- The system shall 既存 `verify_api_key_for_search` 依存と `SearchHTTPException` 経路を再利用する

### US-8: リクエスト構造エラーを明確に判別したい

**ストーリー**: API クライアントとして、リクエストボディの形式エラーを 422 で受け取り、修正してリトライしたい。

**要件 (EARS)**:
- If `channel` フィールドが欠落しているとき、then the system shall HTTP 422 + Pydantic 標準 `detail` 配列を返す
- If `channel` フィールドが空文字または空白のみのとき、then the system shall HTTP 422 を返す（`StringConstraints(strip_whitespace=True, min_length=1)` を適用）
- The system shall `channel` フィールドの先頭・末尾の空白は内部的に strip する
- The system shall `page_token` フィールドが指定された場合、文字列型でなければ HTTP 422 を返す
- The system shall 422 レスポンスには `quota` フィールドを **含めない**（バリデーション失敗のため）

### US-9: 短期レート制限を明確に判別したい

**ストーリー**: LLM エージェントとして、短時間バーストを抑止したいので、レート上限到達時は 429 + Retry-After で再試行可能タイミングを通知してほしい。

**要件 (EARS)**:
- When 直近 60 秒間に `/channel_videos` への成功リクエストが 10 回到達した状態で 11 回目のリクエストが来たとき、the system shall HTTP 429 + `error_code=CLIENT_RATE_LIMITED` + `Retry-After: <秒数>` ヘッダを返す
- The system shall `/channel_videos` 専用の独立したレート制限バケットを保持する
- The system shall `/search` または `/summary` のレート制限カウントには影響を与えない（独立バケット）
- The system shall `Retry-After` 値は最低 1 秒（端数切り上げ）とする

### US-10: 日次クォータ枯渇を明確に判別したい

**ストーリー**: API クライアントとして、YouTube 日次クォータ（10000 units）を使い切った状態を 429 + QUOTA_EXCEEDED で受け取り、PT 0:00 のリセットまで待機したい。

**要件 (EARS)**:
- When プロセス内 `quota_tracker.is_exhausted()` が True を返す状態でリクエストが来たとき、the system shall YouTube API を呼ばずに HTTP 429 + `error_code=QUOTA_EXCEEDED` + `Retry-After: <PT 0:00 までの秒数>` を返す
- When YouTube API が 403 quotaExceeded を返したとき、the system shall `quota_tracker.mark_exhausted("youtube_403")` を呼んで以降のリクエストを早期遮断状態にする
- The system shall `/summary` および `/search` と日次クォータカウンタを **共有**する（既存 `quota_tracker` 一個を全エンドポイントで使い回す）

### US-11: YouTube 一時障害時にも一貫したレスポンスを返したい

**ストーリー**: API クライアントとして、YouTube 側の一時的な 5xx / 429 をリトライ枯渇後も適切な HTTP ステータスで受け取り、上位ロジックでハンドリングしたい。

**要件 (EARS)**:
- When YouTube API がリトライ枯渇後に HTTP 429 を返したとき、the system shall HTTP 503 + `error_code=RATE_LIMITED` を返す
- When YouTube API がリトライ枯渇後に HTTP 5xx を返したとき、the system shall HTTP 503 + `error_code=RATE_LIMITED` を返す
- Where YouTube レスポンスに `Retry-After` ヘッダが含まれるとき、the system shall その値を `response.retry_after` および応答 HTTP ヘッダ `Retry-After` に格納する
- If ネットワーク例外（`requests.RequestException`）が発生したとき、then the system shall HTTP 500 + `error_code=INTERNAL_ERROR` を返す

### US-12: サーバ側の予期せぬ例外でも安定したレスポンスを返したい

**ストーリー**: API クライアントとして、サーバ内部のバグで型不整合等が発生した場合でも、500 + 構造化されたエラーレスポンスを受け取りたい。

**要件 (EARS)**:
- If router 内で予期せぬ例外（`Exception`）が発生したとき、then the system shall ログに `exc_info=True` で記録した上で HTTP 500 + `error_code=INTERNAL_ERROR` + `quota` フィールド付きのレスポンスを返す
- If YouTube が 200 OK を返したが body の構造が dict でない、または `items` が list でない、または `items` 内の要素に dict 以外が含まれるとき、then the system shall HTTP 500 + `error_code=INTERNAL_ERROR` を返す
- The system shall サービス層 (`youtube_channel_videos`) は **常に `ChannelVideosResponse` を返す** 契約とし、例外を呼び出し元に投げない（既存 `youtube_search` と同じ契約）

### US-13: 利用履歴を SQLite に残したい

**ストーリー**: 運用者として、`/channel_videos` の呼び出し履歴を SQLite `api_calls` テーブルに残し、後から分析・トラブルシュートに使いたい。なぜなら、`/summary` および `/search` の履歴記録パターンと一貫させたいから。

**要件 (EARS)**:
- When 認証通過後のリクエスト処理が終了したとき（成功・失敗問わず）、the system shall 既存 `quota_tracker.record_api_call(endpoint='channel_videos', ...)` を呼んで 1 行 INSERT する
- The system shall `endpoint='channel_videos'`, `input_summary` には正規化前の `channel` フィールド値, `units_cost` には実消費 units, `http_status`, `http_success`, `error_code`, `result_count` を記録する
- The system shall `transcript_success` および `transcript_language` は NULL を入れる（このエンドポイントは字幕を扱わないため）
- The system shall 認証エラー（401）およびバリデーションエラー（422）では履歴を記録しない（既存 `/search` と同じ方針）

### US-14: 既存エンドポイントは完全に不変であってほしい

**ストーリー**: 既存の iPhone ショートカット利用者として、`/summary` の挙動が一切変わらないことを保証してほしい。なぜなら、後方互換性が壊れるとショートカットが動かなくなるから。

**要件 (EARS)**:
- The system shall `/summary` のリクエスト形式・レスポンス形式・HTTP 200 固定挙動・既存 22 フィールド + `quota` の構造を変更しない
- The system shall `/search` のリクエスト形式・レスポンス形式・エラーコード・HTTP ステータスマッピングを変更しない
- The system shall 既存 207 件のテスト（`test_youtube_service.py` / `test_api_endpoint.py` / `test_schemas.py` / `test_rate_limiter.py` / `test_search_*.py` / `test_summary_quota_injection.py` / `test_quota_tracker.py` / `test_async_rate_limiter.py`）すべてが PASS する状態を維持する

### US-15: README で利用方法を確認したい

**ストーリー**: 新規利用者または LLM エージェントの開発者として、README.md で `/channel_videos` の使い方・コスト・エラーコードを確認したい。なぜなら、API 仕様の正準ドキュメントは README であってほしいから。

**要件 (EARS)**:
- When 開発者が README.md を参照したとき、the system shall `/api/v1/channel_videos` のセクションが API リファレンス節に含まれている
- The system shall README に以下を記載する:
  - リクエスト形式（`channel` / `page_token` フィールドの説明）
  - レスポンスフィールド一覧（`results` の `SearchResult` 25 フィールド + `channel` ブロック 7 フィールド + `next_page_token` + `quota`）
  - 受け入れ可能な入力例（channel_id / @handle / handle）
  - クォータコスト（3u / 4u / 2u の内訳）
  - エラーコード対応表（既存 10 種 → 11 種、`CHANNEL_NOT_FOUND` 追加）
  - curl 呼び出し例（成功 / handle 解決 / ページング）
- The system shall README の機能リスト・ディレクトリ構造・技術スタック・テストファイル数も新エンドポイント追加に合わせて更新する

---

## 5. 技術的制約（エキスパートレビューより）

### 5.1 YouTube Data API v3 の固有制約

- `playlistItems.list` の `maxResults` は 1〜50（YouTube 公式の hard limit）。本エンドポイントは常に 50 を要求して 1 ページあたりの取得数を最大化する
- `videos.list` の `id` パラメタはカンマ区切りで最大 50 個。`playlistItems.list` で取得した videoId 群を 1 回の `videos.list` で取れる
- `channels.list` の `id` パラメタもカンマ区切り 50 個まで可能だが、本エンドポイントでは 1 チャンネルのみなので単一 ID
- `channels.list?forHandle` は `@` あり / なし両方を受け付けるが、正規化のためサーバ側で `@` を除去してから渡す
- uploads プレイリスト ID は `channels.list` レスポンスの `contentDetails.relatedPlaylists.uploads` に存在する（`part=contentDetails` を必須で含める必要あり）
- channel_id 形式は `^UC[A-Za-z0-9_-]{22}$`（`UC` プレフィックス + 22 文字英数字 / ハイフン / アンダースコア = 24 文字）
- `playlistItems.list` の `pageToken` パラメタは YouTube が返す `nextPageToken` 値を opaque な文字列としてそのまま使う（クライアント側で解析・改変しない）

### 5.2 YouTube クォータコスト（公式表より）

| API メソッド | 1 呼び出しあたりのコスト |
|---|---|
| `search.list` | 100 units |
| `videos.list` | 1 unit |
| `channels.list` | 1 unit |
| `playlistItems.list` | 1 unit |

これにより `/channel_videos` の標準コストは:
- channel_id 入力 + 初回ページ: `channels.list` + `playlistItems.list` + `videos.list` = **3 units**
- handle 入力 + 初回ページ: 上記 + `channels.list?forHandle` = **4 units**
- `page_token` 経由の 2 ページ目以降: `playlistItems.list` + `videos.list` = **2 units**（`channels.list` は再呼び出ししない）

### 5.3 既存実装からの継承・再利用（DRY）

新エンドポイントは以下の既存共通インフラを再利用し、新規追加コードを最小化する:

| 共通インフラ | 提供元 | 用途 |
|---|---|---|
| `quota_tracker` | `app/core/quota_tracker.py` | in-memory + SQLite 永続化、PT 0:00 リセット、ContextVar による per-request 集計 |
| `async_rate_limiter` | `app/core/async_rate_limiter.py` | 60s/10req sliding window（**新エンドポイント用に独立バケットインスタンスを追加**）|
| `verify_api_key_for_search` + `SearchHTTPException` | `app/core/security.py` + `main.py` ハンドラ | 401 + `error_code=UNAUTHORIZED` レスポンス |
| `Quota` Pydantic モデル | `app/models/schemas.py` | `quota` フィールドの型 |
| `SearchResult` Pydantic モデル | `app/models/schemas.py` | `results` 配列の各要素（25 フィールド）|
| `record_api_call` | `app/core/quota_tracker.py` | `api_calls` テーブル記録 |
| `_call_api` HTTP ラッパ | `app/services/youtube_search.py` | `requests.Session` + `urllib3.Retry` ラッパ（流用または相当ロジック新設） |
| `_safe_items` 防御ヘルパ | `app/services/youtube_search.py` | 200 OK 応答の items 形状検証 |
| `_build_search_result` | `app/services/youtube_search.py` | YouTube videos/channels 応答 → `SearchResult` 変換（流用） |
| `frozen Pydantic + model_copy` | 全 router で確立されたパターン | router 内で `quota` を後付け注入する際の必須イディオム |

### 5.4 同期実行の必要性（search-endpoint Phase 4 で発見）

`asyncio.to_thread()` は呼び出し時点のコンテキストをコピーして別スレッドで実行するため、サービス層が `quota_tracker.add_units` で `_request_cost` ContextVar に書き込んでも router 側コルーチンに伝播しない（`last_call_cost == 0` のままになる問題が search-endpoint Phase 4 で実測検出された）。

→ 本エンドポイントのサービス層も **同コルーチン上で同期呼び出し** する（`requests.Session.get` がイベントループを一時ブロックするが、単一プロセス・単一ワーカ運用前提のため許容）。

### 5.5 HTTP リトライ実装

- `requests.Session` + `urllib3.util.retry.Retry` で `status_forcelist=[429, 500, 502, 503, 504]`, `respect_retry_after_header=True`, `allowed_methods=["GET"]`, **`raise_on_status=False`** を使う
- `raise_on_status=False` が必須: True にすると urllib3 がリトライ枯渇後に `MaxRetryError` を投げ、「常に `ChannelVideosResponse` を返す」契約が壊れるため
- リトライ枯渇後の最終 HTTP レスポンスは通常通り受け取って分類する（`_classify_search_api_error` 相当のロジックで 403 quotaExceeded / 429 / 5xx / その他 4xx を error_code にマップ）

### 5.6 防御的型チェック（search-endpoint Phase 3 専門家レビュー由来）

YouTube API は仕様上 200 OK を返しても body の構造が想定外になり得る（一時的な障害、API 側のバグ等）。「常に `ChannelVideosResponse` を返す」契約を厳密に守るため、以下の場合は `ERROR_INTERNAL` に倒す:

- 200 OK だが JSON decode 失敗（body が JSON でない）
- 200 OK だが body が dict でない（list 等）
- `items` フィールドが list でない
- `items` 内の要素に dict 以外が含まれる

`channels.list?forHandle` の場合、空 `items` 配列は **正常な「該当チャンネルなし」** を意味するため `CHANNEL_NOT_FOUND` (404) に倒す（INTERNAL_ERROR ではない）。この区別は明確に実装する。

### 5.7 frozen Pydantic と quota 注入

新規 `ChannelVideosResponse` モデルは既存 `SearchResponse` と同じく `ConfigDict(frozen=True, extra="forbid")` を適用する。router 内で `quota` を後付けするには `response = response.model_copy(update={"quota": quota})` を使う必要がある（直接代入は `ValidationError`）。

### 5.8 単一プロセス・単一ワーカ前提 (FR-7)

本 API はホスト Windows + WSL2 上の Docker Compose で単一プロセス・単一ワーカ運用が前提（既存仕様）。マルチプロセス対応は要件外。`quota_tracker` の in-memory state はプロセスローカルでよい。

---

## 6. 受け入れ基準

### MVP（本 PR で必達）

1. `POST /api/v1/channel_videos` が存在し、`X-API-KEY` で認証される（不正時は HTTP 401 + `error_code=UNAUTHORIZED`、`quota` 同梱なし）
2. `channel` フィールドが `^UC[A-Za-z0-9_-]{22}$` にマッチするとき、channels.list + playlistItems.list + videos.list を 1 回ずつ呼んで合計 3 quota units で動画 50 件を返す
3. `channel` フィールドがそれ以外の文字列のとき、handle として channels.list?forHandle を呼んで channel_id に解決し、合計 4 quota units で動画 50 件を返す
4. `channels.list?forHandle` が空 `items` を返したとき、HTTP 404 + `error_code=CHANNEL_NOT_FOUND` を返す
5. `channel` フィールド未指定または空白のみのとき、HTTP 422 + Pydantic detail を返す
6. レスポンスの `results` 配列に既存 `SearchResult` と同一構造の 25 フィールドが含まれる（`transcript` 系は **絶対に含まない**）
7. 派生値（`like_view_ratio`, `comment_view_ratio`, `channel_avg_views`）が分母 0 / null のとき null になる
8. レスポンスのトップレベルに `channel` オブジェクトが含まれ、7 フィールド（`channel_id` / `channel_name` / `channel_follower_count` / `channel_video_count` / `channel_total_view_count` / `channel_created_at` / `channel_avg_views`）を持つ
9. レスポンスに `next_page_token` が含まれ、YouTube `nextPageToken` のパススルー（無いときは null）
10. `page_token` 指定リクエストでは `channels.list` を呼ばず 2 quota units で完結する
11. レスポンスに `quota` オブジェクトが含まれる（401 / 422 を除く）。`last_call_cost` が 3 / 4 / 2 のいずれかと一致
12. 直近 60 秒に 11 回目のリクエストで HTTP 429 + `Retry-After` + `error_code=CLIENT_RATE_LIMITED` を返す（`/search` および `/summary` のレート制限とは独立カウント）
13. YouTube が 403 quotaExceeded を返す or 内部カウンタが 10000 units 到達のとき、HTTP 429 + `Retry-After` + `error_code=QUOTA_EXCEEDED` を返す
14. YouTube が 5xx / 429 をリトライ枯渇後に返したとき、HTTP 503 + `Retry-After`（取得できれば）+ `error_code=RATE_LIMITED` を返す
15. router 内で予期せぬ例外が発生したとき、HTTP 500 + `error_code=INTERNAL_ERROR` + `quota` を返す
16. 認証通過後の全リクエストが SQLite `api_calls` テーブルに 1 行 INSERT される（`endpoint='channel_videos'`）
17. 既存 `/summary` および `/search` のリクエスト・レスポンス・HTTP ステータスは完全不変
18. 既存テスト 207 件すべてが PASS する状態を維持する
19. 新規テスト（モデル・サービス層・ルーター・エンドポイント統合・防御的型チェック）が追加され、全モックで実行できる
20. README.md に `/api/v1/channel_videos` のリファレンス（リクエスト・レスポンス・curl 例・コスト・エラーコード）が追記される
21. CLAUDE.md の Architecture セクションに新規ファイル（router / service）とエラーコード（11 種）が反映される

### Phase 2（後続フェーズで追加）

22. `channel_alias` SQLite テーブルによる handle → channel_id キャッシュ（永続キャッシュまたは TTL 30 日）
23. スキーマスナップショットテスト（`tests/snapshots/{playlistItems,channels}_list_sample.json`）
24. ライブテスト（`RUN_LIVE_YOUTUBE_TESTS=1` で実 API 1 ショット、約 4 units 消費）

---

## 7. スコープ外（このPRでやらないこと）

- **handle / 表示名のキャッシュ**: 上記 Phase 2 へ
- **表示名（"MrBeast" のような人間が呼ぶ名前）からの検索**: クライアント側で既存 `/search` を使って channel_id を取得してもらう。サーバ側で `search.list?type=channel` を呼ぶフォールバックは実装しない
- **動画 URL → チャンネル変換**: クライアント側で先に動画情報を取って channel_id を抽出してもらう
- **チャンネル URL のサーバ側パース**: クライアント側で URL から `@handle` または `UCxxx` を抽出してから渡してもらう
- **`max_results` 引数**: 1 ページ 50 件固定。5 件取得も 50 件取得もコストが同じなため引数化する意味がないと判断（YAGNI）
- **複数チャンネルの一括取得**: 1 リクエスト 1 チャンネル
- **タイトル / 説明文 / 公開日範囲 等のフィルタリング**: チャンネル内検索が欲しい場合は `/search?channel_id=...` を使う
- **動画の並び順カスタム**: アップロード日時順（YouTube の uploads プレイリスト既定順序）固定
- **DST 境界テスト**: 既存 `quota_tracker` テストでカバー済み（search-endpoint Phase 2 持ち越し項目に統合）

---

## 8. 参考

- [YouTube Data API v3 - Quota Costs](https://developers.google.com/youtube/v3/determine_quota_cost)
- [YouTube Data API v3 - channels.list](https://developers.google.com/youtube/v3/docs/channels/list)
- [YouTube Data API v3 - playlistItems.list](https://developers.google.com/youtube/v3/docs/playlistItems/list)
- [YouTube Data API v3 - videos.list](https://developers.google.com/youtube/v3/docs/videos/list)
- 既存 search-endpoint spec: `.kiro/specs/search-endpoint/{requirements,design,tasks}.md`
- 既存 search-endpoint 実装: `app/{routers/search.py, services/youtube_search.py, core/quota_tracker.py, core/async_rate_limiter.py}`
