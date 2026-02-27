# タスクリスト: YouTube Data API v3 移行（MVP）

> **ソース:** [requirements.md](./requirements.md)（US-1〜US-7）、[design.md](./design.md)（Phase 1〜6、Y-18〜Y-32）

---

## Phase 0: 事前準備（ユーザー作業）

- [x] Google Cloud Console でプロジェクトを作成（または既存プロジェクトを使用）
- [x] YouTube Data API v3 を有効化
- [x] APIキーを発行し、YouTube Data API v3 のみに制限（US-4）
- [x] `.env.local` に `YOUTUBE_API_KEY=<発行したキー>` を設定
- [x] 動作確認: `curl "https://www.googleapis.com/youtube/v3/videos?part=snippet&id=dQw4w9WgXcQ&key=$YOUTUBE_API_KEY"` で JSON が返ることを確認

---

## Phase 1: 定数追加 + テスト基盤更新

> design.md Phase 1 | 変更ファイル: `app/core/constants.py`, `tests/conftest.py`

- [x] `constants.py` に v3 関連定数を追加（US-1, US-2, US-5）
  - `YOUTUBE_API_V3_VIDEOS_URL`, `YOUTUBE_API_V3_CHANNELS_URL`
  - `YOUTUBE_API_V3_VIDEOS_PART = "snippet,contentDetails,statistics"` — videos.list の part パラメータ
  - `YOUTUBE_API_V3_CHANNELS_PART = "statistics"` — channels.list の part パラメータ
  - `YOUTUBE_API_V3_TIMEOUT`, `YOUTUBE_API_V3_MAX_RETRIES`, `YOUTUBE_API_V3_RETRY_STATUS_CODES`
  - `YOUTUBE_API_V3_RETRY_BASE_DELAY = 1` — リトライ指数バックオフの基底遅延（秒）
  - `YOUTUBE_WATCH_URL_TEMPLATE = "https://www.youtube.com/watch?v={video_id}"` — webpage_url 構築用
  - `YOUTUBE_THUMBNAIL_PRIORITY`
  - `YOUTUBE_CATEGORY_MAP`（全32カテゴリ）
  - `MSG_QUOTA_EXCEEDED`
- [x] `conftest.py` に v3 フィクスチャを追加
  - `youtube_api_v3_video_response`
  - `youtube_api_v3_channel_response`
  - `youtube_api_v3_empty_response`
  - `youtube_api_v3_quota_error`
- [x] `conftest.py` に `YOUTUBE_API_KEY` autouse フィクスチャを追加（design.md §7.7）
- [x] **検証:** 既存テスト（Y-1〜Y-17）が全て PASS すること

---

## Phase 2: 純粋関数の TDD

> design.md Phase 2 | 変更ファイル: `app/services/youtube.py`, `tests/test_youtube_service.py`
> 対応要件: US-2（受入基準 4〜8）

### RED: テスト追加

- [x] Y-18: `test_y18_parse_iso8601_duration` — 8パターン parametrize（design.md §4.1）
- [x] Y-19: `test_y19_format_duration_string` — 6パターン parametrize（design.md §4.2）
- [x] Y-20: `test_y20_select_best_thumbnail` — 6パターン parametrize（design.md §4.3）

### GREEN: 実装

- [x] `_parse_iso8601_duration(duration_str)` を実装（design.md §4.1）
- [x] `_format_duration_string(total_seconds)` を実装（design.md §4.2）
- [x] `_select_best_thumbnail(thumbnails)` を実装（design.md §4.3）

### 検証

- [x] Y-18, Y-19, Y-20 が全て PASS
- [x] 既存テスト（Y-1〜Y-17）が引き続き PASS

---

## Phase 3: API 呼び出し層の TDD

> design.md Phase 3 | 変更ファイル: `app/services/youtube.py`, `tests/test_youtube_service.py`
> 対応要件: US-5（受入基準 3）、US-6（受入基準 1, 4）

### RED: テスト追加

- [x] Y-22: `test_y22_classify_api_error` — 9パターン parametrize（design.md §4.7）
- [x] Y-23: `test_y23_retry_then_success` — 503→200、sleep(1) 1回（design.md §7.3）
- [x] Y-24: `test_y24_all_retries_exhausted` — 503×4回、sleep(1,2,4)（design.md §7.3）
- [x] Y-25: `test_y25_4xx_no_retry` — 403 quotaExceeded、requests.get 1回のみ（design.md §7.3）
- [x] Y-25b: `test_y25b_no_api_key_in_logs` — caplog でエラーログに `key=` や APIキー値が含まれないことを検証（US-4 受入基準 5: APIキー漏洩防止の回帰テスト）
- [x] Y-25c: `test_y25c_network_error_retry_then_success` — ConnectionError→200、sleep(1) 1回（US-6 受入基準 1: ネットワークエラーのリトライ検証）
- [x] Y-25d: `test_y25d_network_error_all_retries_exhausted` — ConnectionError×4回、sleep(1,2,4)（US-6 受入基準 1: ネットワークエラーの全リトライ失敗検証）

### GREEN: 実装

- [x] `ApiCallResult` NamedTuple を定義（design.md §3.1）
- [x] `_extract_api_error_reason(error_body)` を実装 — reason 抽出ロジックの共通化ヘルパー（コードレビューで DRY 改善として追加）
- [x] `_classify_api_error(status_code, error_body)` を実装（design.md §4.7）— `_extract_api_error_reason` を使用、`accessNotConfigured` を明示的に分岐
- [x] `_call_youtube_api_with_retry(url, params)` を実装（design.md §4.4）— ループ末尾に `AssertionError("unreachable")` で到達不能を明示
- [x] `_YT_REASON_QUOTA_EXCEEDED`, `_YT_REASON_FORBIDDEN`, `_YT_REASON_ACCESS_NOT_CONFIGURED` — モジュール内 private 定数（コードレビューで定数の局所化として追加）

### 検証

- [x] Y-22〜Y-25d が全て PASS（15 passed）
- [x] 既存テスト（Y-1〜Y-17）+ Phase 2 テストが引き続き PASS（合計 60 passed / 全テスト 73 passed）

---

## Phase 4: メタデータ構築の TDD

> design.md Phase 4 | 変更ファイル: `app/services/youtube.py`, `tests/test_youtube_service.py`
> 対応要件: US-1（受入基準 1〜3）、US-2（受入基準 2〜9）、US-3、US-4（受入基準 4）、US-5（受入基準 1, 2）、US-6（受入基準 1〜3）

### RED: テスト追加

- [x] Y-21: `test_y21_category_conversion` — 4パターン parametrize、`_build_metadata_from_youtube_api` 経由（design.md §7.2）
- [x] Y-26: `test_y26_fetch_metadata_success` — videos.list + channels.list 正常系（design.md §7.3）
- [x] Y-27: `test_y27_video_not_found` — items 空（design.md §7.3）
- [x] Y-28: `test_y28_quota_exceeded` — 403 quotaExceeded（design.md §7.3）
- [x] Y-29: `test_y29_channels_partial_success` — channels.list 失敗でも `channel_follower_count=None` で成功（design.md §7.3）
- [x] Y-30: `test_y30_api_key_not_set` — `monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)` で autouse フィクスチャを上書きし、即 INTERNAL_ERROR を検証（design.md §7.3、US-4 受入基準 4）
- [x] Y-30b: `test_y30b_api_key_not_set_no_transcript_call` — 同じく `monkeypatch.delenv` で未設定化。短絡終了し字幕API/oEmbed が呼ばれないことを検証（design.md §7.3）
- [x] Y-31: `test_y31_quota_exceeded_message` — `RATE_LIMITED` + `MSG_QUOTA_EXCEEDED` + 短絡終了（design.md §7.3）
- [x] Y-32: `test_y32_5xx_fallback_to_oembed` — リトライ枯渇→oEmbed→字幕成功（design.md §7.3）

### GREEN: 実装

- [x] `FetchMetadataResult` NamedTuple を定義（design.md §3.1）
- [x] `_build_metadata_from_youtube_api(video_data, channel_data, video_id)` を実装（design.md §4.5）
- [x] `_fetch_metadata_youtube_api(video_id)` を実装（design.md §4.6）
- [x] `_resolve_error_message(error_code)` を実装（design.md §4.6）

### 検証

- [x] Y-21, Y-26〜Y-32 が全て PASS
- [x] 既存テスト + Phase 2〜3 テストが引き続き PASS

---

## Phase 5: 統合 — `get_summary_data` 書き換え + 既存テスト更新

> design.md Phase 5 | 変更ファイル: `app/services/youtube.py`, `tests/test_youtube_service.py`, `tests/test_api_endpoint.py`, `tests/conftest.py`
> 対応要件: US-1〜US-6（全受入基準の統合テスト）

### 実装

- [x] `get_summary_data()` のメインフローを書き換え（design.md §4.6）
  - `_fetch_metadata_youtube_api()` を呼び出し
  - 3分岐: (1) 即時エラー返却、(2) oEmbed フォールバック、(3) 正常系
  - `_resolve_error_message()` でクォータ超過と字幕API起因の message 出し分け
  - error_code / message 優先順位ルール（design.md §4.6.1）

### 既存テスト更新（v3 API モック形式に全面書き換え）

- [x] Y-1: yt-dlp mock → requests.get mock（videos.list + channels.list）、全フィールド期待値更新
- [x] Y-2: yt-dlp 失敗 → v3 API 全リトライ失敗→oEmbed フォールバック
- [x] Y-3: メタデータ成功 mock を v3 形式に変更、字幕エラー検証は維持
- [x] Y-4: DownloadError → items=[] に変更
- [x] Y-6: v3 形式でメタデータ成功 + 字幕 YouTubeRequestFailed、**`message == MSG_RATE_LIMITED` アサート追加**（回帰防止）
- [x] Y-7: v3 形式に更新
- [x] Y-8: `likeCount` フィールド欠損の v3 レスポンス
- [x] Y-10: v3 API 失敗 + oEmbed フォールバック成功 + 字幕成功
- [x] Y-12: v3 レスポンスの一部フィールド欠損ケース
- [x] Y-14: メタデータ成功 mock を v3 形式に変更
- [x] Y-15: v3 形式に更新、**`message == MSG_RATE_LIMITED` アサート追加**（回帰防止）
- [x] Y-16: v3 API 失敗 → oEmbed タイムアウト
- [x] Y-5, Y-11, Y-13, Y-17: 変更不要であることを確認

### テスト基盤更新

- [x] `test_youtube_service.py` の import に `MSG_RATE_LIMITED`, `MSG_QUOTA_EXCEEDED` を追加
- [x] `conftest.py` から `ytdlp_success_info` フィクスチャを削除

### `test_api_endpoint.py` の v3 移行（E-1〜E-7）

> `test_api_endpoint.py` は全6テスト（E-1, E-3〜E-7）で `@patch("app.services.youtube.yt_dlp.YoutubeDL")` に依存。
> Phase 6 で yt-dlp を削除する前にモック形式を移行しないとテストが破綻する。

- [x] `_make_ytdlp_mock` ヘルパーを `_make_v3_api_mock` に置換（requests.get の side_effect で videos.list + channels.list を返す）
- [x] `YTDLP_INFO` dict を v3 形式の videos/channels レスポンスに置換
- [x] E-1: `@patch("app.services.youtube.yt_dlp.YoutubeDL")` → `@patch("app.services.youtube.requests.get")`、全フィールド期待値を v3 変換結果に更新
- [x] E-3: URL 検証テストのため API モック不要（`@patch` デコレータなし、変更不要を確認）
- [x] E-4: 同上（字幕エラー検証は維持、メタデータ mock を v3 形式に）
- [x] E-5: 同上（後方互換性フィールドの型検証を v3 形式で）
- [x] E-6: 同上（status フィールド検証を v3 形式で）
- [x] E-7: 同上（transcript_language, is_generated 検証を v3 形式で）

### 検証

- [x] **全テスト PASS**（Y-1〜Y-17 更新済み + Y-18〜Y-32 新規 + E-1〜E-7 更新済み）

---

## Phase 6: yt-dlp 削除 + Docker/依存関係更新

> design.md Phase 6 | 対応要件: US-7（全受入基準）、US-4（受入基準 3）

### 削除作業

- [ ] `youtube.py` から削除（US-7 受入基準 3）
  - `import yt_dlp`
  - `from app.core.constants import YTDLP_DIRECT_KEYS, YTDLP_KEY_MAP`
  - `_fetch_metadata_ytdlp()` 関数
  - `_build_metadata_from_ytdlp()` 関数
  - `_convert_upload_date()` 関数
- [ ] `constants.py` から `YTDLP_KEY_MAP`, `YTDLP_DIRECT_KEYS` を削除（US-7 受入基準 4）
- [ ] `requirements.txt` から `yt-dlp[default]` を削除（US-7 受入基準 1）
- [ ] `docker/Dockerfile.api` から Deno インストール行を削除（US-7 受入基準 2）

### 追加作業

- [ ] `.env.example` に `YOUTUBE_API_KEY` のプレースホルダーをコメントで追加（US-4 受入基準 3）

### 検証

- [ ] **全テスト PASS**
- [ ] `docker compose build api` でビルド成功

---

## Phase 7: 最終検証

- [ ] `pytest tests/ -v` — 全テスト PASS
- [ ] `docker compose build api` — ビルド成功
- [ ] `docker compose up -d` — コンテナ起動
- [ ] 手動統合テスト: 実動画（`dQw4w9WgXcQ`）でメタデータ取得（design.md §10.3）
  - `title`, `channel_name`, `channel_id`, `description`, `webpage_url` が `str` であること
  - `upload_date` が `YYYY-MM-DD` 形式（str）であること
  - `duration` が秒数（int）であること
  - `duration_string` が `"M:SS"` or `"H:MM:SS"` 形式（str）であること
  - `view_count` が int であること
  - `like_count` が int または `null`（動画によって非公開の場合あり、US-2 受入基準 3）
  - `tags` がリストまたは `null`（タグ未設定の動画では欠損が正常、US-2 受入基準 3）
  - `categories` がカテゴリ名のリスト（例: `["Music"]`）であること
  - `channel_follower_count` が int または `null`（hiddenSubscriberCount 時、US-3 受入基準 3）
  - `thumbnail_url` が `https://i.ytimg.com/` で始まる URL であること
- [ ] 手動統合テスト: 存在しない動画（`xxxxxxxxxxx`）で `VIDEO_NOT_FOUND` が返ること
