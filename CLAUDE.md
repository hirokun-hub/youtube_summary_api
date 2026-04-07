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
- `app/routers/summary.py` — APIエンドポイント（POST /api/v1/summary）
- `app/services/youtube.py` — YouTube API v3 + transcript取得のビジネスロジック
- `app/models/schemas.py` — Pydanticリクエスト/レスポンスモデル
- `app/core/constants.py` — エラーコード定義（7種）
- `app/core/security.py` — X-API-KEY認証

## Code Conventions
- 関数名・変数名: snake_case、クラス名: PascalCase
- コメント・ログメッセージ: 日本語
- 型ヒント必須（`dict | None` スタイル）
- テスト命名: `test_[code]_[description]`
- 設計原則: KISS, DRY, YAGNI — 過度な抽象化を避ける

## Environment
- `.env` — 共有設定（LOG_LEVEL）
- `.env.local` — 機密値（API_KEY, GEMINI_API_KEY, YOUTUBE_API_KEY）※Git管理外
