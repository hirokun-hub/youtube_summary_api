# Implementation Plan（TDD・MVP）

本タスクリストは `.kiro/specs/search-endpoint/design.md`（1500+ 行、mermaid 図 7 枚、ContextVar 方式の quota 注入を含む確定設計書）に基づき、`POST /api/v1/search` 追加と既存 `/summary` への `quota` 注入を **テスト駆動（RED → GREEN → REFACTOR）** で実装する手順を定義する。

- 完了基準: `pytest tests/ -v` で **既存 97 件 + 新規 50+ 件 = 147+ 件** すべて PASS（内訳: SR 7 系列＝50 件 / SQ 9 / AR 5 / SS 12 / ST 9 / SU 5）。SR は parametrize 展開と Phase 1 専門家レビューで追加した防御線（Quota の TZ aware ×2、q の空白拒否、published_*/before の TZ aware、401 quota キー欠落契約）を含めて 50 件まで膨らんでいる
- 仮運用: `compose.staging.yml`（ポート 10001）で本番 `:10000` を生かしたまま並走 → 機能 OK で本番 `compose.yml` に上書き
- スコープ: MVP のみ。DST 境界テスト・スキーマスナップショット・ライブテストは Phase 2（受け入れ基準 #19/#20/#21）として **後続フェーズ** で着手

## Phase 0: 準備

- [x] 0. 着手前チェック
  - [x] 0.1 ブランチ確認
    - `git branch --show-current` が `feature/search-endpoint` であること
    - 既存テストが現状で全 PASS であること: `pytest tests/ -v`（97 件 PASS が基準値）
    - _要件: 受け入れ基準 #17_
  - [x] 0.2 `.gitignore` に `data/usage/` を追加する
    - `.env.local` 直後の機密値ブロック末尾に **2 行** 追加する: `data/usage/*` と `!data/usage/.gitkeep`（後者で `.gitkeep` だけ追跡可能にする。タスク 0.3 で `.gitkeep` を commit する前提を満たすために 1 行構成では不可）
    - _要件: 受け入れ基準 #16_
  - [x] 0.3 `data/usage/` ディレクトリを作成する
    - `.gitkeep` のみ commit（usage.db は `.gitignore` で除外）
    - _要件: 設計書 §5_
  - [x] 0.4 依存追加が不要であることを再確認する
    - `requirements.txt` に追加なし（`requests` / `sqlite3` / `zoneinfo` / `asyncio` / `itertools.batched` はすべて既存または Python 3.12 標準）
    - `requirements-dev.txt` も変更なし
    - _要件: 要件定義書「新規依存」_

## Phase 1: モデル + 定数（RED → GREEN）

- [x] 1. 定数を拡張する
  - [x] 1.1 `app/core/constants.py` に search 用定数を追加する
    - エラーコード: `ERROR_QUOTA_EXCEEDED`, `ERROR_UNAUTHORIZED`（既存の 7 種は不変）
    - メッセージ: `MSG_QUOTA_EXCEEDED`, `MSG_UNAUTHORIZED`, `MSG_CLIENT_RATE_LIMITED`（テンプレート、`{rule}` `{retry_after}` 含む）
    - レート制限: `SEARCH_RATE_LIMIT_WINDOW_SECONDS = 60`, `SEARCH_RATE_LIMIT_MAX_REQUESTS = 10`
    - クォータ: `YOUTUBE_DAILY_LIMIT = 10000`, `YOUTUBE_QUOTA_TIMEZONE = "America/Los_Angeles"`
    - SQLite: `USAGE_DB_PATH = "data/usage/usage.db"`, `SQLITE_BUSY_TIMEOUT_MS = 5000`
    - YouTube API コスト: `COST_SEARCH_LIST = 100`, `COST_VIDEOS_LIST = 1`, `COST_CHANNELS_LIST = 1`
    - **既存定数の変更**: `YOUTUBE_API_V3_CHANNELS_PART = "statistics"` を `"snippet,statistics"` に変更（`channel_created_at` 取得のため）
    - _要件: 受け入れ基準 #5, #9, #10, #13、設計書 §3.1, FR-10_

- [x] 2. スキーマテストを書く（RED）
  - [x] 2.1 `tests/test_search_schemas.py` にテスト SR-1〜SR-7 系を実装する（実装後 Phase 1 専門家レビューで以下 4 種の追加検証を含めた最終形に拡張: ① `Quota.reset_at_utc/jst` の TZ aware 強制、② `SearchRequest.q` の `strip_whitespace=True`、③ `SearchRequest.published_after/before` の TZ aware 強制、④ 401 レスポンスで `model_dump(exclude_none=True)` 時に `quota` キーが欠落することの契約）
    - SR-1: `SearchRequest` の `q` 必須・他フィールド任意、`order` 列挙、`published_after/before` ISO 8601 検証
    - SR-2: `Quota` モデルの全 7 フィールド、`remaining_units_estimate = daily_limit - consumed_units_today` の `@computed_field`、`reset_in_seconds` は素フィールド（`@computed_field` ではない）
    - SR-3: `SearchResult` の必須フィールド存在と派生値（`like_view_ratio` 等）が `float | None`
    - SR-4: `SearchResponse` の `success/status/error_code` 整合（`@model_validator(mode="after")`）と `quota` フィールド
    - SR-5: **新規レスポンスモデル（`Quota` / `SearchResult` / `SearchResponse`）に `frozen=True, extra="forbid"`** を適用（requirements.md TC-10 に従う）。`SearchRequest` は入力モデルなので `extra="forbid"` のみ（frozen 不要）。**`SummaryResponse` は requirements.md TC-10 の「本 PR スコープ例外」条項により frozen を追加しない**（既存 97 件テストの破壊を避けるため）。**quota 注入は router 側で `response = response.model_copy(update={"quota": quota})` で行う**（直接代入は ValidationError になるため）
    - SR-6: `transcript` / `transcript_language` / `is_generated` が `SearchResult` に **存在しない** こと
    - SR-7: `SummaryResponse.quota: Quota | None` が Optional で追加され、既存フィールドの型・名称が完全に不変
    - 実行 → **全件失敗（RED）** を確認: `pytest tests/test_search_schemas.py -v`
    - _要件: 受け入れ基準 #2, #5, #6, #8、設計書 §3.4, §9.2_

- [x] 3. レスポンスモデルを実装する（GREEN）
  - [x] 3.1 `app/models/schemas.py` に新規モデルを追加する（実装最終形は design.md §3.4 に反映済み: `Quota` の TZ aware validator、`SearchRequest.q` の `StringConstraints(strip_whitespace=True, min_length=1)`、`SearchRequest.published_*/before` の aware validator、`SearchResponse.frozen=True` を含む）
    - `SearchRequest`（q + 7 任意フィールド、`@field_validator` で ISO 8601 / 列挙チェック）
    - `Quota`（7 フィールド、`@computed_field` は `remaining_units_estimate` のみ）
    - `SearchResult`（22 フィールド、派生値 3 種、`has_caption: bool`、`ConfigDict(frozen=True, extra="forbid")`）
    - `SearchResponse`（成功時 + エラー時両方を表現、`results: list[SearchResult] | None`、**`ConfigDict(frozen=True, extra="forbid")`**）
    - `Quota` も `ConfigDict(frozen=True, extra="forbid")`、`SearchRequest` は `ConfigDict(extra="forbid")` のみ
    - **`SummaryResponse` は frozen を追加しない**（既存挙動・既存 97 件テスト維持のため。**requirements.md TC-10 に「本 PR スコープでの例外」として明記済み**。Phase 2 以降で既存テストの `model_copy(update=...)` 移行と合わせて frozen 化する）
    - **設計書 §3.4 で `SearchResponse` が `extra="forbid"` のみ になっている部分は、本タスクで requirements.md TC-10 に整合させる形で実装時に `frozen=True` を追加する**（design.md と requirements.md の不整合解消）
    - _要件: 設計書 §3.4, TC-10_
  - [x] 3.2 `SummaryResponse` に `quota: Quota | None = None` を追加する
    - 既存フィールドは名前・型・順序すべて不変（追加のみ）
    - `model_config.json_schema_extra` の例も更新
    - _要件: 受け入れ基準 #8, #17、設計書 §3.7_
  - [x] 3.3 テスト実行 → **全件成功（GREEN）** を確認
    - `pytest tests/test_search_schemas.py tests/test_schemas.py -v`
    - 既存 `test_schemas.py` の S-1〜S-6（6 件）も PASS していること
    - _要件: 受け入れ基準 #17_

## Phase 2: 純粋ロジック層（quota_tracker + async_rate_limiter）

### 2-A: async_rate_limiter（RED → GREEN）

- [x] 4. async レート制限テストを書く（RED）
  - [x] 4.1 `tests/test_async_rate_limiter.py` にテスト AR-1〜AR-5 を実装する
    - AR-1: 10 回までは `check_request()` が `(True, None)` を返す
    - AR-2: 11 回目で `(False, blocked_payload)`、`retry_after` が「ウィンドウ先頭が 60 秒経過するまでの秒数」と一致
    - AR-3: 60 秒経過後にウィンドウから古い記録が排除され、再度許可される（`time.monotonic` をパッチ）
    - AR-4: `pytest.mark.asyncio` で `asyncio.gather` 同時 20 並列でも `asyncio.Lock` により race condition がない（許可 10 件・拒否 10 件で確定）
    - AR-5: `Retry-After` 値が最低 1 秒（端数切り上げ）
    - 実行 → **全件失敗（RED）** を確認
    - _要件: 受け入れ基準 #9, #12、設計書 §3.3, §9.4_

- [x] 5. async レート制限を実装する（GREEN）
  - [x] 5.1 `app/core/async_rate_limiter.py` を新規作成する
    - `_state = {"deque": collections.deque(), "lock": None}`（モジュールレベル）。`lock` は **lazy 初期化**（最初の `check_request` で `asyncio.Lock()` を生成）。Python 3.10+ で `asyncio.Lock()` は最初の `await` 時に現在の event loop に結びつくため、テスト環境で `asyncio.run()` を複数回呼ぶケースに対する安全性確保
    - `async def check_request(now=None) -> tuple[bool, dict | None]`（`now` はテスト用に外部から `time.monotonic()` 値を注入できる任意引数）
    - `collections.deque` で直近 60 秒の `time.monotonic()` 値を保持、ウィンドウ外は popleft
    - 上限超過時は `error_code=ERROR_CLIENT_RATE_LIMITED` / `retry_after` / `message` を含む dict を返す（`retry_after` は `max(1, ceil(window - elapsed))` で最低 1 秒）
    - `reset() -> None`: テスト用の deque + lock リセット
    - 既存の `app/core/rate_limiter.py`（`/summary` 用 `threading.Lock`）には触らない
    - _要件: 受け入れ基準 #9, #12、設計書 §3.3, TC-4_
  - [x] 5.2 テスト実行 → **全件成功（GREEN）** を確認
    - `pytest tests/test_async_rate_limiter.py -v`

### 2-B: quota_tracker（RED → GREEN）

- [x] 6. quota_tracker テストを書く（RED）
  - [x] 6.1 `tests/test_quota_tracker.py` にテスト SQ-1〜SQ-9 を実装する
    - SQ-1: 起動時 `init_db()` で `api_calls` / `quota_state` テーブルが作成され、PRAGMA（WAL/synchronous=NORMAL/busy_timeout=5000/foreign_keys=ON）が適用される
    - SQ-2: `add_units(100)` で in-memory `consumed_units_today` と SQLite `quota_state` が同時に +100 される（api_calls には書かない）
    - SQ-3: `record_api_call(endpoint, ...)` で `api_calls` に 1 行 INSERT され、`quota_state` には影響しない（`endpoint="search"` / `endpoint="summary"` の両方で同一関数が使えること）
    - SQ-4: `get_snapshot(now_utc)` が `Quota` オブジェクトを返し、`reset_at_utc` / `reset_at_jst` / `reset_in_seconds` が PT 0:00 基準で正確（`zoneinfo.ZoneInfo("America/Los_Angeles")` 使用）
    - SQ-5: PT 0:00 を跨ぐタイミング（パッチ済み `now_utc`）で内部カウンタが 0 にリセットされる
    - SQ-6: 起動時 SUM 復元 — 事前に `api_calls` へ手動 INSERT した行から `consumed_units_today` を再計算する
    - SQ-7: 内部カウンタが `daily_limit` (10000) 到達で `is_exhausted()` が `True`
    - SQ-8: `BEGIN IMMEDIATE` トランザクションで書き込みロックを先取り（`SQLITE_BUSY` を起こさない）
    - SQ-9: **ContextVar 隔離** — `asyncio.gather` で 2 並行リクエストが `add_units(100)` と `add_units(50)` を実行しても、各リクエストの `get_request_cost()` は自分の値（100 / 50）のみを返す
    - 実行 → **全件失敗（RED）** を確認
    - _要件: 受け入れ基準 #10, #11, #13, #14, #15、設計書 §3.2, §5_

- [x] 7. quota_tracker を実装する（GREEN）
  - [x] 7.1 `app/core/quota_tracker.py` を新規作成する
    - モジュール定数: `_state = {"consumed_units_today": 0, "quota_date_pt": None, "exhausted_until": None, "db_path": None}`, `_lock = threading.RLock()`（in-memory ガード）
    - `_request_cost: ContextVar[int] = ContextVar("request_cost", default=0)`
    - **`init(db_path, now_utc=None) -> None`**: テーブル作成 + PRAGMA 適用 + 起動時 SUM 復元を **1 関数に統合**（実装結果。当初案では `init_db()` と `restore_from_db()` を分離していたが、design.md §3.2 と整合させる形で 1 つの `init()` に集約。`now_utc` 引数はテスト用）
    - `add_units(cost, now_utc=None) -> None`: in-memory + `quota_state` UPDATE + `_request_cost` 加算（3 箇所同時更新）
    - **`record_api_call(endpoint, input_summary, units_cost, http_status, http_success, error_code, transcript_success, transcript_language, result_count, now_utc=None) -> None`**: `api_calls` に 1 行 INSERT。**`quota_tracker.py` に置く**（design.md §3.5 では `youtube_search.py` 内に置く案だったが、`/search` と `/summary` の両方から呼ぶため SQLite アクセスを集約する責務として `quota_tracker.py` に集約。設計書 §3.5 の `_record_api_call` の役割をここに移動する）
    - `get_snapshot(now_utc=None) -> Quota`: ContextVar の `last_call_cost` も含めて `Quota` を組み立てる（NamedTuple ではなく `app.models.schemas.Quota` を直接返す）
    - `is_exhausted(now_utc=None) -> bool`
    - `mark_exhausted(reason, now_utc=None) -> None`: 403 受信時に呼ぶ。次の PT 0:00 まで in-memory で枯渇扱い（**MVP では永続化しない** — FR-8 の「権威」レイヤは「内部カウンタに関係なく即 QUOTA_EXCEEDED に倒す」までで、再起動越えの永続化は明示要件外。実害は再起動直後の 1 リクエストで再度 403 を受け同状態に戻るだけ）
    - `reset_request_cost() -> None`: `_request_cost.set(0)`
    - `get_request_cost() -> int`: `_request_cost.get()`
    - `_next_pt_midnight_utc(now_utc) -> datetime`: `zoneinfo` で計算（モジュール内 private）
    - すべての SQLite 書き込みは `BEGIN IMMEDIATE` で開始、async コンテキストからは `asyncio.to_thread()` で呼ぶ
    - _要件: 受け入れ基準 #10, #11, #13, #14, #15、設計書 §3.2, §5, §8, TC-2/3/5_
  - [x] 7.2 `main.py` の lifespan で `init(USAGE_DB_PATH)` を 1 回呼び出す
    - FastAPI の `lifespan`（`@asynccontextmanager` ベース）を採用（`@app.on_event("startup")` は非推奨警告のため避けた）
    - _要件: 受け入れ基準 #14、設計書 §5.5_
  - [x] 7.3 テスト実行 → **全件成功（GREEN）** を確認
    - `pytest tests/test_async_rate_limiter.py tests/test_quota_tracker.py -v`
    - **実績**: AR 5 件 + SQ 10 件（タスク 6.1 の SQ-1〜9 に加え、403 強制 exhausted の追加カバレッジとして `test_sq7_mark_exhausted_forces_true_until_pt_midnight` を追加。design.md §9.3 SQ-6 と同等）= 15 件 PASS

## Phase 3: youtube_search サービス層（RED → GREEN）

- [x] 8. サービス層テストを書く（RED）
  - [x] 8.1 `tests/test_search_service.py` にテスト SS-1〜SS-12 を実装する（design.md §3.5 の契約「常に SearchResponse を返す（例外を投げない）」に整合）
    - SS-1: 正常系 `search_videos(req)` が `search.list` → `videos.list` → `channels.list` を順に 1 回ずつ呼び、`SearchResponse(success=True, error_code=None, results=[...])` を返す
    - SS-2: 重複動画 ID の排除（`videos.list` の id パラメタが unique）
    - SS-3: 重複チャンネル ID の排除（`channels.list` の id パラメタが unique）
    - SS-4: 派生値計算 — `like_view_ratio = like_count / view_count`、分母 0 で `null`
    - SS-5: 派生値計算 — `comment_view_ratio` 同様、`channel_avg_views = channel_total_view_count / channel_video_count`
    - SS-6: `has_caption` — `contentDetails.caption` の文字列 `"true"` / `"false"` を bool 化
    - SS-7: 403 quotaExceeded を受信 → `SearchResponse(success=False, error_code=ERROR_QUOTA_EXCEEDED, results=None)` を返す（**例外を投げない**）。`quota_tracker.mark_exhausted("youtube_403")` も呼ばれる
    - SS-8: 上流 429（リトライ枯渇後）→ `SearchResponse(success=False, error_code=ERROR_RATE_LIMITED, results=None)` + `retry_after`（Retry-After ヘッダから取得、不在なら None）を返す
    - SS-9: 上流 5xx（リトライ枯渇後）→ `SearchResponse(success=False, error_code=ERROR_RATE_LIMITED)` を返す
    - SS-10: 上流ネットワーク例外（`requests.RequestException`）→ `SearchResponse(success=False, error_code=ERROR_INTERNAL)` を返す
    - SS-11: `add_units(100)` `add_units(1)` `add_units(1)` を順に 3 回呼ぶ（成功時）。失敗時は到達した段階までしか積まない（例: search.list 段階で 403 → `add_units` 0 回）
    - SS-12: フィルタパラメタが正しく URL クエリにマップされる（`order=date`, `videoDuration=long`, `channelId=UCxxx`, `publishedAfter`, `publishedBefore`, `regionCode`, `relevanceLanguage`）
    - **モック対象**: `app.services.youtube_search._session` の `get` メソッド（`requests.Session` インスタンスをモジュールレベルで保持する実装に合わせる。design.md §3.5 / TC-1 と整合）。`MagicMock` で `status_code` / `json()` / `headers` を返す
    - **削除（Phase 2 へ繰り延べ）**: 50 件超のチャンネル ID バッチ分割テスト — `/search` の `maxResults=50` 固定により unique channel IDs ≤ 50 で通常フローでは到達しない。`itertools.batched` の境界は将来 max_results 引き上げ時の保険であり MVP 受け入れに直接寄与しないため
    - **削除**: 上流 401 認証失敗テスト — `YOUTUBE_API_KEY` の不正設定はデプロイ時に発覚すべき問題で、ランタイムテスト対象から外す（MVP 受け入れ基準には対応せず）
    - **追加（Phase 3 専門家レビュー対応）**: 防御的型チェックテストを 9 件追加し、契約「常に SearchResponse を返す（例外を投げない）」と要件「予期せぬ例外は INTERNAL_ERROR」を厳密に固定する:
      ① 200 OK + JSON decode 失敗 → ERROR_INTERNAL（quota 加算なし）
      ② 200 OK + 非 dict body（list 等） → ERROR_INTERNAL
      ③ search.list の `items` が非 list → ERROR_INTERNAL
      ④ search.list `items` 内に非 dict 要素 → ERROR_INTERNAL
      ⑤ `pageInfo` が非 dict → 緩く `total_results_estimate=None` で成功扱い（派生メタは致命でない）
      ⑥ videos.list 200 OK + 非 dict body → ERROR_INTERNAL（search.list 段階の add_units(100) のみ積まれる）
      ⑦ channels.list 200 OK + JSON decode 失敗 → ERROR_INTERNAL（add_units(100, 1) まで積まれる）
      ⑧ videos.list の `items` が非 list → ERROR_INTERNAL
      ⑨ search.list item の `id` が非 dict → ERROR_INTERNAL
    - 実行 → **全件失敗（RED）** を確認
    - _要件: 受け入れ基準 #2, #5, #7, #10, #11、設計書 §3.5, §7, §9.5, TC-1_

- [x] 9. サービス層を実装する（GREEN）
  - [x] 9.1 `app/services/youtube_search.py` を新規作成する
    - **HTTP クライアント**: モジュールレベルで `_session = requests.Session()` を構築し、`HTTPAdapter(max_retries=Retry(total=N, status_forcelist=[429, 500, 502, 503, 504], backoff_factor=1.0, backoff_jitter=0.3, respect_retry_after_header=True, allowed_methods=["GET"], **raise_on_status=False**))` を `mount("https://", ...)`。**`raise_on_status=False` が必須**（urllib3 のデフォルトは True で、リトライ枯渇後は `MaxRetryError` 例外になり、SS-8/SS-9 の「`SearchResponse` を返す」前提が崩れるため）。design.md §3.5 / TC-1 と整合
    - **`_call_api(url: str, params: dict) -> tuple[int, dict | None, dict, str | None]`**（実装結果。当初案の `_call_youtube_search_api(url, params) -> tuple[int, dict|None, str|None, bool]` から変更）: `_session.get(url, params=params, timeout=...)` で取得し、`(status_code, body_or_none, headers_dict, error_code_or_none)` を返す。**`is_retryable_failure` フラグは廃止**（リトライは urllib3 が完了し、最終 HTTP レスポンスが直接戻るため不要）。**`headers` を戻り値に含める**（`Retry-After` を SearchResponse.retry_after に格納するため）。**403 quotaExceeded はリトライしない**（即時 `QUOTA_EXCEEDED` 判定）。**200 OK でも body が dict でない場合は `ERROR_INTERNAL` に倒す**（Phase 3 専門家レビュー対応、契約「常に SearchResponse を返す」を厳密化）
    - `_classify_search_api_error(status_code: int, error_body: dict | None) -> str`: 403 quotaExceeded → `ERROR_QUOTA_EXCEEDED`、429/5xx → `ERROR_RATE_LIMITED`、その他 4xx → `ERROR_INTERNAL`
    - `_compute_ratio(numerator, denominator) -> float | None`: 分母 0 / None で None
    - `_parse_caption(value: str | None) -> bool`: `"true"` → True、それ以外 → False
    - **`_safe_items(body: dict | None) -> list[dict] | None`**（Phase 3 専門家レビュー対応で追加）: `body.items` を `list[dict]` として安全に取り出す。body が非 dict / items が非 list / 要素に非 dict を含む → `None`（呼び出し側で `ERROR_INTERNAL` に倒すシグナル）。items 不在 / `None` → 空 list
    - **契約**: `search_videos(req: SearchRequest) -> SearchResponse`（**常に `SearchResponse` を返す。例外は投げない**。design.md §3.5 L491 と整合）。**実装は `_do_search` 本体 + `try / except Exception` の最終捕捉ラッパに分割**（Phase 3 専門家レビュー対応で追加。`_build_search_result` 内の想定外例外も `_failure_response(ERROR_INTERNAL, req.q)` に倒す）
      1. `search.list` 呼び出し（成功時 `add_units(100)`、失敗時はその時点で `SearchResponse(success=False, error_code=...)` を return）
      2. videoId 重複排除 → `videos.list(id=...)` 呼び出し（成功時 `add_units(1)`、失敗時 return）
      3. channelId 重複排除 → `channels.list` 呼び出し（成功時 `add_units(1)`、失敗時 return）。Unique IDs ≤ 50 のため通常 1 回で完結。`itertools.batched(ids, 50)` は 50 件超の保険として残す
      4. 結合 + 派生値計算 + `has_caption` 設定 → `SearchResponse(success=True, error_code=None, results=[...])`
      5. 403 quotaExceeded 受信時は `quota_tracker.mark_exhausted("youtube_403")` を呼んでから return
      6. リトライ枯渇後の 429 / 5xx は `Retry-After` ヘッダ値を取得して `SearchResponse.retry_after` に格納
      7. **各ステージ後の防御**: `_safe_items()` で 200 OK 応答の `items` 形状を検証、不正なら `ERROR_INTERNAL` を返す（Phase 3 専門家レビュー対応）
    - **`record_api_call` は呼ばない**（router の finally 相当で 1 回呼ぶ。指摘 1/3 への対応）
    - 既存の `_parse_iso8601_duration` / `_format_duration_string` / `_select_best_thumbnail` / `_to_int_or_none` / `_extract_api_error_reason` / `YOUTUBE_CATEGORY_MAP` / `YOUTUBE_WATCH_URL_TEMPLATE` を **再利用**（`app/services/youtube.py` および `app/core/constants.py` から import）
    - 既存の `_call_youtube_api_with_retry` / `_classify_api_error` は **再利用しない**（`/summary` の挙動を保つため別実装）
    - **設計書差分**: design.md §3.5 で個別関数として描かれていた `_call_search_list` / `_call_videos_list` / `_call_channels_list` は実装で **`_call_api` に統合**（呼び出し側の `_do_search` 内でインライン呼び出し）。共通化により URL 別の薄いラッパが不要となり、コードが簡潔化
    - _要件: 設計書 §2.3, §3.5, FR-10, TC-1, TC-7, TC-8_
  - [x] 9.2 テスト実行 → **全件成功（GREEN）** を確認
    - `pytest tests/test_search_service.py -v`
    - **実績**: **31 件 PASS**（SS-1〜SS-12 系列の parametrize 展開で 22 件 + Phase 3 専門家レビュー対応の防御テスト 9 件）。全体 **193 件 PASS**、既存挙動の回帰なし

## Phase 4: router + エンドポイント統合（RED → GREEN）

- [x] 10. 認証依存を追加する
  - [x] 10.1 `app/core/security.py` に `verify_api_key_for_search` を追加する
    - **FastAPI の `HTTPException` には `error_code` 引数は存在しない**（`(status_code, detail, headers)` のみ）。`detail` を **dict** にして error_code を埋め込む形にする:
      ```python
      raise HTTPException(
          status_code=401,
          detail={"error_code": ERROR_UNAUTHORIZED, "message": MSG_UNAUTHORIZED, "success": False, "status": "error"},
      )
      ```
    - main.py のグローバル `HTTPException` ハンドラで `detail` が dict の場合はそのまま JSON 本体として返し（`quota` は付けない）、それ以外（既存 `/summary` の 403 等）は従来通りの整形を維持
    - 既存の `verify_api_key`（403 を投げる、`/summary` 用）には **触らない**
    - _要件: 受け入れ基準 #1、設計書 §3.7, FR-5_

- [x] 11. ルーター + 例外ハンドラのテストを書く（RED）
  - [x] 11.1 `tests/test_search_endpoint.py` にテスト ST-1〜ST-9 を実装する。**履歴記録アサーション**（受け入れ基準 #15）を全テストに含める形で、各テスト実行後に `api_calls` テーブルの行数と内容を検証する
    - ST-1: 正常リクエスト → HTTP 200 + `SearchResponse`、`quota.last_call_cost == 102`、`quota.consumed_units_today == pre + 102`。`_session.get` を 3 段 mock。**`api_calls` に 1 行 INSERT され、`endpoint="search"` / `units_cost=102` / `http_status=200` / `http_success=True` / `error_code=NULL` / `result_count=N`**
    - ST-2: `X-API-KEY` ヘッダなし → HTTP 401 + `error_code=UNAUTHORIZED`、`quota` フィールド **なし**。**`api_calls` には行追加なし**（認証通過前のため記録しない）
    - ST-3: `q` 未指定 → HTTP 422 + `{"detail": [...]}` 形式、`quota` **なし**、`success`/`error_code` **なし**。**`api_calls` には行追加なし**（バリデーション失敗のため記録しない）
    - ST-4: `order` 列挙外 → HTTP 422、`api_calls` 行追加なし
    - ST-5: 11 回目のリクエスト（`async_rate_limiter` の上限超過）→ HTTP 429 + `Retry-After` ヘッダ + `error_code=CLIENT_RATE_LIMITED` + `retry_after` フィールド + `quota` **あり** + メッセージ本文に `"max 10 requests per 60 seconds"` と `retry_after` 秒数を含む。**`api_calls` に 1 行 INSERT、`endpoint="search"` / `units_cost=0` / `http_status=429` / `http_success=False` / `error_code="CLIENT_RATE_LIMITED"`**
    - ST-6: `quota_tracker.is_exhausted()` を mock で True → HTTP 429 + `Retry-After` + `error_code=QUOTA_EXCEEDED` + `quota.remaining_units_estimate == 0`。**`api_calls` に 1 行、`units_cost=0` / `http_status=429` / `error_code="QUOTA_EXCEEDED"`**
    - ST-7: YouTube が 403 quotaExceeded を返す（service 内で `mark_exhausted` が呼ばれる）→ HTTP 429 + `error_code=QUOTA_EXCEEDED`。**`api_calls` に 1 行、`units_cost=0`（search.list 段階で 403 を受けた場合）または部分消費分**
    - ST-8: YouTube が 429 を返す → HTTP 503 + `Retry-After` + `error_code=RATE_LIMITED`。**`api_calls` に 1 行、`http_status=503` / `error_code="RATE_LIMITED"`**
    - ST-9: 内部例外（service が `error_code=INTERNAL_ERROR` の SearchResponse を返す or router 内で予期せぬ例外）→ HTTP 500 + `error_code=INTERNAL_ERROR` + `quota` **あり**。**`api_calls` に 1 行、`http_status=500` / `error_code="INTERNAL_ERROR"`**
    - モック: `_session.get` (3 段、または個別)、`async_rate_limiter.search_rate_limiter.try_acquire`、`quota_tracker.is_exhausted`
    - **全テストで使用**: `tests/conftest.py` に `usage_db_path` fixture（`tmp_path` で SQLite ファイルパスを差し替え、`quota_tracker.init(...)` を呼ぶ）を追加し、テスト後に行数を検証
    - 実行 → **全件失敗（RED）** を確認
    - _要件: 受け入れ基準 #1, #3, #8, #9, #10, **#15**、設計書 §3.6, §6, §9.6, FR-5, FR-9_

- [x] 12. ルーター + 例外ハンドラを実装する（GREEN）
  - [x] 12.1 `app/routers/search.py` を新規作成する
    - `router = APIRouter(prefix="/api/v1", tags=["Search"])`
    - `@router.post("/search", dependencies=[Depends(verify_api_key_for_search)])`（`response_model=SearchResponse` は付けない。HTTP status を経路ごとに変えるため `JSONResponse` で直接返す）
    - **router 内で `try / except / finally` を組み、認証通過後の全結果（200/429/503/500、想定例外も含む）を 1 箇所で記録する**（受け入れ基準 #15）。グローバル例外ハンドラ側では `record_api_call` を **呼ばない**（二重記録防止）
    - 処理フロー（疑似コード）:
      ```python
      async def search(body: SearchRequest, _: str = Depends(verify_api_key_for_search)):
          quota_tracker.reset_request_cost()
          response: SearchResponse | None = None
          http_status = 500
          headers: dict[str, str] = {}
          try:
              # 早期 1: クライアントレート制限
              allowed, retry_after = await search_rate_limiter.try_acquire()
              if not allowed:
                  response = SearchResponse(success=False, error_code=ERROR_CLIENT_RATE_LIMITED,
                                             query=body.q, retry_after=retry_after,
                                             message=MSG_SEARCH_CLIENT_RATE_LIMITED_TEMPLATE.format(...))
                  http_status, headers = 429, {"Retry-After": str(retry_after)}
              # 早期 2: クォータ枯渇
              elif quota_tracker.is_exhausted():
                  snap = quota_tracker.get_snapshot()
                  response = SearchResponse(success=False, error_code=ERROR_QUOTA_EXCEEDED,
                                             query=body.q, message=MSG_QUOTA_EXCEEDED_TEMPLATE.format(...))
                  http_status, headers = 429, {"Retry-After": str(snap.reset_in_seconds)}
              # 通常経路: サービス層
              else:
                  response = await asyncio.to_thread(youtube_search.search_videos, body)
                  http_status, headers = _map_response_to_http(response)  # error_code → status
          except Exception:
              logger.exception("/search router で予期せぬ例外")
              response = SearchResponse(success=False, error_code=ERROR_INTERNAL,
                                         query=body.q, message=MSG_INTERNAL_ERROR)
              http_status, headers = 500, {}
          finally:
              # quota 注入は frozen のため model_copy で行う（SearchResponse は frozen=True）
              if response is not None:
                  snap = quota_tracker.get_snapshot()
                  quota = _build_quota_from_snapshot(snap, last_call_cost=quota_tracker.get_request_cost())
                  response = response.model_copy(update={"quota": quota})
                  # 認証通過後の全結果を 1 行記録（受け入れ基準 #15）
                  quota_tracker.record_api_call(
                      endpoint="search", input_summary=body.q,
                      units_cost=quota_tracker.get_request_cost(),
                      http_status=http_status,
                      http_success=(200 <= http_status < 300),
                      error_code=response.error_code,
                      transcript_success=None, transcript_language=None,
                      result_count=response.returned_count,
                  )
          return JSONResponse(content=response.model_dump(mode="json"),
                              status_code=http_status, headers=headers)
      ```
    - **`response.quota = ...` の直接代入は ValidationError**（SearchResponse が `frozen=True`）。**必ず `model_copy(update={"quota": quota})`** を使う
    - サービス層は `SearchResponse` を返す契約のため、router で `try/except YoutubeQuotaExceeded` のような **例外捕捉は行わない**（design.md §3.5 L491 と整合）。`except Exception` は router 内のバグ（service が想定外を返す等）の最終セーフティネット
    - _要件: 受け入れ基準 #15、設計書 §3.5, §3.6, FR-5, FR-9_
  - [x] 12.2 `main.py` に search ルータを include する
    - `from app.routers import search as search_router`
    - `app.include_router(search_router.router)`
    - _要件: 受け入れ基準 #1_
  - [x] 12.3 FastAPI 例外ハンドラを `main.py`（または別ファイル）に追加する
    - `RequestValidationError` → 422 `{"detail": [...]}`（既存 FastAPI 標準を維持）。**`record_api_call` を呼ばない**（バリデーション失敗は認証通過前と同等の扱い）
    - **`SearchHTTPException` 専用ハンドラ**（実装最終形。当初案では `@app.exception_handler(HTTPException)` グローバル登録 + `detail` が dict なら body 直接返却としていたが、Phase 4 専門家レビュー対応で **`SearchHTTPException(HTTPException)` サブクラス + 専用ハンドラ** に変更し、スコープを `/search` だけに閉じた。これにより既存 `/summary` の `HTTPException(detail=str, 403)` および将来 endpoint の `HTTPException(detail=dict)` は FastAPI 標準ハンドラの `{"detail": ...}` 形式に維持される。design.md §6.2 の差分表参照）。`SearchHTTPException` の `detail`（dict）を **そのまま JSON ボディとして返し**、`quota` は含めず、`record_api_call` も呼ばない
    - **`record_api_call` はグローバル例外ハンドラからは呼ばない**（router の `try/finally` で一元記録するため、二重 INSERT を防ぐ）
    - **router を通らない予期せぬ例外**（依存関係解決中の例外など）は既存の `generic_exception_handler` がカバー。これらは `api_calls` に記録されないが、認証通過前ケースと同じ扱いで運用上問題なし
    - _要件: 受け入れ基準 #1, #3, #8, #15、設計書 §6.2, FR-5, FR-9_
  - [x] 12.4 テスト実行 → **全件成功（GREEN）** を確認
    - `pytest tests/test_search_endpoint.py -v`
    - **実績**: ST-1〜ST-9 の **9 件 PASS**。既存 97 件 + Phase 1〜3 累計 96 件 + Phase 4 9 件 = **全 202 件 PASS**（回帰なし）
    - **設計差分（実装後追記）**: design.md §3.6 / tasks.md 12.1 の擬似コードでは `await asyncio.to_thread(search_videos, body)` でサービス層を呼び出していたが、`asyncio.to_thread` は呼び出し時点のコンテキストを **コピー** して別スレッドで実行する。`quota_tracker.add_units` が ContextVar (`_request_cost`) に書き込んでも router 側コルーチンに伝播せず `last_call_cost == 0` のままになる問題があったため、**`search_videos(body)` を同コルーチン上で同期呼び出し** する形に変更した。サーバが単一プロセス・単一ワーカ運用 (FR-7) で /search の想定 latency も短いため、イベントループの一時的ブロックよりも ContextVar 整合（受け入れ基準 #8 の `last_call_cost`）を優先する判断。Phase 5 の `/summary` 改造でも同方針を踏襲する見込み

## Phase 5: /summary への quota 注入 + 既存回帰

- [x] 13. /summary quota 注入 + 履歴記録テストを書く（RED）
  - [x] 13.1 `tests/test_summary_quota_injection.py` にテスト SU-1〜SU-5 を実装する。**履歴記録アサーション**（受け入れ基準 #15）を全テストに含める形で、各テスト後に `api_calls` を検証する
    - SU-1: 正常完了 → `body.quota.last_call_cost == 2`、`body.quota.consumed_units_today == pre + 2`、HTTP 200。**`api_calls` に 1 行 INSERT、`endpoint="summary"` / `units_cost=2` / `http_status=200` / `http_success=True` / `error_code=NULL` / `transcript_success=True` / `transcript_language="ja"`**
    - SU-2: 既存 `success=True` レスポンスに `quota` が常に含まれる（業務処理を通った場合は必ず付与）
    - SU-3: HTTP は **200 固定**（`/search` と異なり、エラー時も 200）— 既存の `/summary` 挙動維持
    - SU-4: レート制限早期 return（`/summary` 用 `rate_limiter` の 60 秒間隔）→ HTTP 200 + `success=False` + `quota.last_call_cost == 0`。**`api_calls` に 1 行、`endpoint="summary"` / `units_cost=0` / `http_status=200` / `http_success=False` / `error_code="CLIENT_RATE_LIMITED"`**
    - SU-5: サービス層が失敗（例: VIDEO_NOT_FOUND）→ HTTP 200 + `success=False` + `quota.last_call_cost == 1`（videos.list は呼んだが channels.list 前に失敗）。**`api_calls` に 1 行、`units_cost=1` / `error_code="VIDEO_NOT_FOUND"` / `transcript_success=False`**
    - 実行 → **全件失敗（RED）** を確認
    - _要件: 受け入れ基準 #8, #15, #17、設計書 §3.7, §9.7, FR-9_

- [x] 14. /summary を 3 経路 quota 注入 + 履歴記録に改造する（GREEN）
  - [x] 14.1 `app/routers/summary.py` を改造する
    - **try / finally で履歴記録を保証**（受け入れ基準 #15、`/summary` の **全リクエスト** が記録対象）
    - `SummaryResponse` は frozen を追加しないため `response.quota = ...` の直接代入も可能。ただし **新規 router 経路では一貫性のため `response.model_copy(update={"quota": quota})` を推奨**（`/search` と同じイディオム）
    - 経路 1（rate limit 早期）: `quota_tracker.reset_request_cost()` → `check_request()` 拒否なら `SummaryResponse(success=False, quota=_build_quota_from_snapshot(snap, last_call_cost=0), **blocked)` を **コンストラクタで一気に組む**（後代入を避ける）
    - 経路 2（通常完了）: `reset_request_cost()` → `get_summary_data()` 実行 → `response = response.model_copy(update={"quota": _build_quota_from_snapshot(snap, last_call_cost=get_request_cost())})`
    - 経路 3（早期エラー、サービス層が `success=False` を返した場合）: 経路 2 と同じく `model_copy(update=...)` で注入。`get_request_cost()` で途中まで進んだ units 数を反映
    - 既存の HTTP 200 固定・既存フィールドの型・順序は **完全不変**
    - **finally で履歴記録（router 内一元記録）**: `quota_tracker.record_api_call(endpoint="summary", input_summary=video_id_or_url, units_cost=quota_tracker.get_request_cost(), http_status=200, http_success=response.success, error_code=response.error_code, transcript_success=(response.transcript is not None), transcript_language=response.transcript_language, result_count=None)` を 3 経路すべての終端で呼ぶ。グローバル例外ハンドラからは **呼ばない**（二重 INSERT 防止、`/search` と同じ方針）
    - **実装差分（Phase 5 完了後追記）**:
      ① `record_api_call` の例外を **`try/except` で warning に倒す**。理由は TestClient が lifespan を再実行しないため `quota_tracker` が未 init のままになる既存 97 件テスト環境で `record_api_call` の `RuntimeError` が router を破壊するのを避けるため（本番では lifespan 起動時に init 済み）。/search 側 router と同じイディオム（`logger.exception` → `logger.warning`）
      ② `input_summary` は **`_extract_video_id(video_url) or video_url`** で記録。requirements.md L387 / design.md L1046 が `q or video_id` を指定するため、URL 全体ではなく抽出した video_id を優先記録（INVALID_URL ケースは原 URL を fallback として残す）
      ③ `_build_quota_from_snapshot` ヘルパは **作らない**。`quota_tracker.get_snapshot()` が既に `Quota` を直接返すため、`response.model_copy(update={"quota": snap})` だけで完結
      ④ `try/finally` で履歴記録を **一元化**（design.md §3.7 の「各経路で個別 return」案ではなく、終端を 1 箇所に集約して受け入れ基準 #15 を確実に満たす）
    - _要件: 受け入れ基準 #8, #15, #17、設計書 §3.7, FR-9_
  - [x] 14.2 `app/services/youtube.py` の `get_summary_data` 内で `add_units(1)` を videos.list / channels.list の各呼び出し直後に追加する
    - 既存ロジック・既存戻り値は不変、`add_units` 呼び出しのみを挿入
    - **実装差分**: `_fetch_metadata_youtube_api` 内で videos.list 成功直後 (`is_retryable_failure=False` かつ `error_code is None` の判定後)、および channels.list の `channels_result.data` が真値のときに `quota_tracker.add_units(QUOTA_COST_VIDEOS_LIST)` / `add_units(QUOTA_COST_CHANNELS_LIST)` を呼ぶ
    - _要件: 受け入れ基準 #8、設計書 §3.7_
  - [x] 14.3 テスト実行 → **全件成功（GREEN）** を確認
    - `pytest tests/test_summary_quota_injection.py -v`
    - **実績**: SU-1〜SU-5 の **5 件 PASS**

- [x] 15. 既存回帰確認 + 全件 PASS 確認
  - [x] 15.1 既存テスト 97 件の PASS を再確認する
    - `pytest tests/test_youtube_service.py tests/test_api_endpoint.py tests/test_schemas.py tests/test_rate_limiter.py -v`
    - **全 97 件 PASS** が必須（quota 追加で壊れていないこと）
    - _要件: 受け入れ基準 #17_
  - [x] 15.2 全テスト合計の PASS を確認する
    - `pytest tests/ -v`
    - **実績**: **207 件 PASS**（既存 97 + Phase 1 SR 50 + Phase 2 AR/SQ 15 + Phase 3 SS+防御 31 + Phase 4 ST 9 + Phase 5 SU 5）。失敗 0、回帰 0
    - _要件: 受け入れ基準 #17, #18_

## Phase 6: 仮運用（staging、別ポート）

- [ ] 16. staging 用 compose を作成する
  - [ ] 16.1 `compose.staging.yml` を新規作成する
    - 内容（既存 `docker-compose.yml` をベースに以下を変更）:
      - `container_name: youtube-api-fastapi-staging`
      - `ports: "0.0.0.0:10001:10000"`（コンテナ内 10000、ホスト側 10001）
      - `volumes: ./data/usage:/app/data/usage`（SQLite 永続化）
      - `env_file` は本番と同一（`.env` / `.env.local`）
    - 既存 `docker-compose.yml` は **変更しない**（本番 `:10000` を生かし続ける）
    - _要件: 設計書 §11.2_

- [ ] 17. staging を起動して機能チェックする
  - [ ] 17.1 staging イメージをビルド・起動する
    - `docker compose -f compose.staging.yml build api`
    - `docker compose -f compose.staging.yml up -d`
    - `docker ps` で `youtube-api-fastapi`（本番）と `youtube-api-fastapi-staging`（staging）が **両方 running** であることを確認
  - [ ] 17.2 curl で 5 種の HTTP ステータスを手動確認する
    - 200: `curl -X POST http://localhost:10001/api/v1/search -H "X-API-KEY: $API_KEY" -H "Content-Type: application/json" -d '{"q":"test"}'`
    - 401: 上記から `X-API-KEY` ヘッダを削除
    - 422: `-d '{}'`（`q` 未指定）
    - 429: 11 回連続実行
    - 503: YouTube が 429 を返すケースは再現困難なので、`is_exhausted` mock パッチ実装の確認は単体テストで代替（手動では skip 可）
    - レスポンス JSON に `quota` オブジェクト（401/422 以外）が含まれることを目視確認
    - _要件: 受け入れ基準 #1, #2, #3, #8, #9, #10_
  - [ ] 17.3 既存 `/summary`（`:10000`）が並行稼働していることを確認する
    - `curl -X POST http://localhost:10000/api/v1/summary -H "X-API-KEY: $API_KEY" -d '{"video_url":"https://www.youtube.com/watch?v=..."}'`
    - 既存の iPhone ショートカット動作と同等のレスポンスが返ることを確認
  - [ ] 17.4 Tailscale 経由で iPhone から疎通確認する
    - `:10001` のサービスを Tailscale ホスト名 + ポートで叩いて 200 が返ること
    - _要件: 設計書 §11.2_

- [ ] 18. SQLite 永続化と起動時 SUM 復元を確認する
  - [ ] 18.1 staging で何度か `/search` を叩いた後、コンテナを再起動する
    - `docker compose -f compose.staging.yml restart api`
    - 起動後の `/search` レスポンスで `quota.consumed_units_today` が再起動前と同じ値（PT 0:00 跨ぎがなければ）になっていることを確認
    - `data/usage/usage.db` がホスト側に存在し、`sqlite3 data/usage/usage.db "SELECT COUNT(*) FROM api_calls"` で行数が増えていることを確認
    - _要件: 受け入れ基準 #14, #15_

## Phase 7: 本番上書き

- [ ] 19. staging を停止する
  - [ ] 19.1 `docker compose -f compose.staging.yml down`
  - [ ] 19.2 `docker ps` で `youtube-api-fastapi-staging` が消えていることを確認

- [ ] 20. 本番 compose に追加要素を反映する
  - [ ] 20.1 `docker-compose.yml` に `volumes` を追加する
    - `volumes: ./data/usage:/app/data/usage`（SQLite 永続化）
    - ポートは `:10000` のまま、container_name も既存 `youtube-api-fastapi` のまま
    - _要件: 受け入れ基準 #15_
  - [ ] 20.2 本番再ビルド・再起動する
    - `docker compose build api`
    - `docker compose up -d`（既存コンテナを置換）
    - `docker logs youtube-api-fastapi --tail 50` で起動エラーがないこと、`init_db()` / `restore_from_db()` の起動ログが出ていることを確認

- [ ] 21. 本番動作確認
  - [ ] 21.1 既存 `/summary` の後方互換確認
    - iPhone ショートカットからリクエストし、既存 22 フィールド（`success` / `status` / `message` / `transcript` 等）が **完全に同一形式** で返ることを確認
    - 新規 `quota` オブジェクトが追加されていることを確認（iPhone ショートカットは未知フィールドを無視するため非破壊）
    - _要件: 受け入れ基準 #17、要件定義書「最重要方針: 既存機能の後方互換維持」_
  - [ ] 21.2 新規 `/search` の動作確認
    - Tailscale 経由で `:10000` の `/api/v1/search` を叩き、200 と 401/422/429 のサンプルを取得
    - レスポンスの `quota.reset_in_seconds` が現在時刻と PT 0:00 の差として整合すること
    - _要件: 受け入れ基準 #1〜#10_

- [ ] 22. ドキュメント反映
  - [ ] 22.1 `CLAUDE.md` の `Architecture` セクションを更新する
    - `app/routers/search.py` を追加
    - `app/core/quota_tracker.py` を追加
    - `app/core/async_rate_limiter.py` を追加
    - `app/services/youtube_search.py` を追加
    - エラーコードが 7 種 → 9 種（`QUOTA_EXCEEDED`, `UNAUTHORIZED` 追加）に更新
    - _要件: なし（運用ドキュメント整備）_
  - [ ] 22.2 受け入れ基準のチェックリストを `requirements.md` で確認する
    - MVP #1〜#18 を順にチェックし、完了マーク
    - Phase 2（#19/#20/#21）は次フェーズで対応する旨を明記
    - _要件: 受け入れ基準 #1〜#18_

---

## 検証サマリ

| Phase | 検証コマンド | 期待結果 |
|---|---|---|
| 1 | `pytest tests/test_search_schemas.py tests/test_schemas.py -v` | SR-1〜SR-7 系 (50, parametrize と専門家レビュー追加分を含む) + S-1〜S-6 (6) PASS |
| 2 | `pytest tests/test_async_rate_limiter.py tests/test_quota_tracker.py -v` | AR-1〜AR-5 (5) + SQ-1〜SQ-9 + 追加 mark_exhausted カバレッジ (10) = **15 PASS**（実績） |
| 3 | `pytest tests/test_search_service.py -v` | **31 件 PASS**（実績）: SS-1〜SS-12 系列 22 件（parametrize 展開含む） + Phase 3 専門家レビュー対応の防御テスト 9 件 |
| 4 | `pytest tests/test_search_endpoint.py -v` | ST-1〜ST-9 (9) PASS |
| 5 | `pytest tests/ -v` | **Phase 5 完了時点の実績: 207 件 PASS**（既存 97 + Phase 1 SR 50 + Phase 2 AR/SQ 15 + Phase 3 SS+防御 31 + Phase 4 ST 9 + Phase 5 SU 5）。回帰 0 |
| 6 | `docker compose -f compose.staging.yml up -d` + curl | 5 種 HTTP（200/401/422/429）が staging で確認できる |
| 7 | `docker compose up -d` + iPhone ショートカット | 本番 `/summary` 後方互換 + 新規 `/search` 動作 |

## ロールバック手順（Phase 7 失敗時）

1. `docker compose down`
2. `git revert <last commit>` または `git stash` で `docker-compose.yml` の volumes 追加を取り消す
3. `docker compose up -d` で従来構成に戻す（破壊的操作なし、データは `data/usage/` に残る）

## Phase 2 で対応する項目（本 PR 対象外）

- 受け入れ基準 #19: `tests/snapshots/{search,videos,channels}_list_sample.json`（実 API レスポンスのスキーマスナップショット）
- 受け入れ基準 #20: `tests/live/test_youtube_search_live.py`（`RUN_LIVE_YOUTUBE_TESTS=1` で有効化、約 102 units 消費）
- 受け入れ基準 #21: DST 境界テスト（2026-03-08 開始 / 2026-11-01 終了）を `tests/test_quota_tracker.py` に追加
- **旧 SS-4 相当**: `_call_channels_list` / `_call_videos_list` の 50 件超バッチ分割テスト — `/search` の `maxResults=50` 固定により通常フローでは到達しないため MVP 受け入れに不要。将来 max_results を可変化する際にユニットテストとして追加
