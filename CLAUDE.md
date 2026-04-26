# CLAUDE.md

## Project Overview
YouTube動画のURL → メタデータ+字幕を返すFastAPI。Docker Composeで起動し、ホスト（Windows）側のTailscale経由でプライベート公開。

## Tech Stack
Python 3.12 / FastAPI / Pydantic v2 / pytest / Docker Compose

## Key Commands
- `docker compose up -d` — 本番起動
- `pytest tests/ -v` — テスト実行（全てモック、外部通信なし）
- `uvicorn main:app --host 0.0.0.0 --port 10000` — ローカル直接起動

## Architecture
- `app/routers/summary.py` — APIエンドポイント（POST /api/v1/summary、HTTP 200 固定）
- `app/routers/search.py` — APIエンドポイント（POST /api/v1/search、200/401/422/429/503/500 正規化）
- `app/services/youtube.py` — YouTube API v3 + transcript取得のビジネスロジック（/summary 用）
- `app/services/youtube_search.py` — search.list → videos.list → channels.list の検索サービス（/search 用）
- `app/models/schemas.py` — Pydanticリクエスト/レスポンスモデル（SummaryResponse / SearchRequest / SearchResponse / SearchResult / Quota）
- `app/core/constants.py` — エラーコード定義（9種：INVALID_URL / VIDEO_NOT_FOUND / TRANSCRIPT_NOT_FOUND / TRANSCRIPT_DISABLED / RATE_LIMITED / CLIENT_RATE_LIMITED / METADATA_FAILED / INTERNAL_ERROR / QUOTA_EXCEEDED / UNAUTHORIZED）
- `app/core/security.py` — X-API-KEY認証（/summary は 403、/search は 401 を返す `SearchHTTPException` 経路）
- `app/core/rate_limiter.py` — /summary 用クライアント側レート制限（threading.Lock）
- `app/core/async_rate_limiter.py` — /search 用クライアント側レート制限（asyncio.Lock + sliding window 60s/10req）
- `app/core/quota_tracker.py` — YouTube Daily Quota 追跡（in-memory + SQLite 永続化、PT 0:00 リセット、ContextVar による per-request 集計）
- `data/usage/usage.db` — SQLite（WAL mode、`api_calls` / `quota_state` テーブル、本番では bind mount で host 側に永続化）

## Code Conventions
- 関数名・変数名: snake_case、クラス名: PascalCase
- コメント・ログメッセージ: 日本語
- 型ヒント必須（`dict | None` スタイル）
- テスト命名: `test_[code]_[description]`
- 設計原則: KISS, DRY, YAGNI — 過度な抽象化を避ける

## Environment
- `.env` — 共有設定（LOG_LEVEL）
- `.env.local` — 機密値（API_KEY, GEMINI_API_KEY, YOUTUBE_API_KEY）※Git管理外
