# main.py

"""
このモジュールは、FastAPIアプリケーションのエントリーポイントです。
アプリケーションのインスタンス化、ミドルウェアの設定、ルーターの登録など、
アプリケーション全体の起動と構成を担当します。
"""

# --- 環境変数の読み込みを最優先で実行 ---
# 他のモジュールが環境変数を参照する前に .env ファイルを読み込む必要があるため、
# この処理をファイルの先頭に移動します。
from pathlib import Path
from dotenv import load_dotenv

# .envを読み込み（共有可能な設定値）
env_path = Path('.') / '.env'
load_dotenv(dotenv_path=env_path)

# .env.localを読み込み（機密値、存在する場合は上書き）
# override=Trueにより、.envと.env.localで同じキーがある場合は.env.localの値を優先
env_local_path = Path('.') / '.env.local'
load_dotenv(dotenv_path=env_local_path, override=True)


import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# --- アプリケーション内モジュールのインポート ---
# core/logging_config.py からロギング設定関数をインポート
from app.core.logging_config import setup_logging
# クォータ追跡（SQLite 永続化）。startup イベントで init を呼ぶ
from app.core import quota_tracker
from app.core.constants import USAGE_DB_PATH
from app.core.security import SearchHTTPException
# routers/summary.py からAPIルーターをインポート
from app.routers import summary as summary_router
from app.routers import search as search_router

# --- ロギングのセットアップ ---
# アプリケーション起動時に一度だけロギング設定を呼び出す
setup_logging()
logger = logging.getLogger(__name__)


# --- アプリケーションライフサイクル: 起動時にクォータ追跡を初期化 ---
@asynccontextmanager
async def _lifespan(app: FastAPI):
    """SQLite (data/usage/usage.db) を初期化し、起動時 SUM 復元を行う。"""
    db_path = Path(USAGE_DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    quota_tracker.init(db_path)
    logger.info(
        "quota_tracker を初期化しました（DB: %s, consumed_units_today: %d）",
        db_path,
        quota_tracker.get_snapshot().consumed_units_today,
    )
    yield


# --- FastAPIアプリケーションのインスタンス化 ---
logger.debug("FastAPIアプリケーションのインスタンスを作成します。")
app = FastAPI(
    title="YouTube Summary API",
    description="YouTube動画のメタデータと文字起こしを取得するためのAPIです。",
    version="1.1.0",
    lifespan=_lifespan,
)

# --- グローバル例外ハンドラの登録 ---
@app.exception_handler(SearchHTTPException)
async def search_http_exception_handler(
    request: Request, exc: SearchHTTPException
):
    """`/search` 専用 `HTTPException` を JSON ボディに整形するハンドラ。

    `detail` (dict) を **そのまま JSON 本体** として返す。要件 FR-4 / FR-5 の
    401 レスポンス契約 (`{"success": False, "error_code": "UNAUTHORIZED", ...}`) を満たす。

    **スコープ**: `SearchHTTPException` のみを対象とする。これにより、既存
    `/summary` の `verify_api_key` (`HTTPException(detail=str)` で 403) や、将来
    別 endpoint が `HTTPException(detail=dict)` を投げるケースは FastAPI 標準
    ハンドラ (`{"detail": ...}` 形式) で従来どおり処理される。Phase 4 専門家
    レビュー対応 (2026-04-26): グローバル `HTTPException` 上書きから限定スコープへ移行。
    """
    headers = exc.headers or None
    return JSONResponse(
        status_code=exc.status_code, content=exc.detail, headers=headers
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    """
    予期せぬすべての例外をキャッチし、詳細をログに出力するグローバルハンドラ。
    これにより、デバッグが容易になり、クライアントには一貫したエラーメッセージを返す。
    """
    # エラーの詳細（スタックトレースを含む）をログに出力
    logger.error(f"リクエスト処理中にハンドルされていない例外が発生しました: {exc}", exc_info=True)

    # クライアントには汎用的なエラーメッセージを返す
    return JSONResponse(
        status_code=500,
        content={"detail": "内部処理中に予期せぬエラーが発生しました。"},
    )


# --- APIルーターの登録 ---
logger.debug("APIルーターを登録します。")
# summary_router.router をアプリケーションに含める
# これにより、/api/v1/summary エンドポイントが利用可能になる
app.include_router(summary_router.router)
# /api/v1/search エンドポイントを有効化
app.include_router(search_router.router)


# --- ルートエンドポイントの定義 ---
@app.get("/", tags=["Root"])
async def read_root():
    """
    アプリケーションのルートエンドポイント。
    APIが正常に動作しているかを確認するためのヘルスチェックとして利用できます。
    """
    logger.info("ルートエンドポイントへのアクセスがありました。")
    return {"message": "Welcome to the YouTube Summary API!"}

logger.info("FastAPIアプリケーションのセットアップが完了しました。")
