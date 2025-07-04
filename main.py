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

env_path = Path('.') / '.env'
load_dotenv(dotenv_path=env_path)


import logging
from fastapi import FastAPI

# --- アプリケーション内モジュールのインポート ---
# core/logging_config.py からロギング設定関数をインポート
from app.core.logging_config import setup_logging
# routers/summary.py からAPIルーターをインポート
from app.routers import summary as summary_router

# --- ロギングのセットアップ ---
# アプリケーション起動時に一度だけロギング設定を呼び出す
setup_logging()
logger = logging.getLogger(__name__)


# --- FastAPIアプリケーションのインスタンス化 ---
logger.debug("FastAPIアプリケーションのインスタンスを作成します。")
app = FastAPI(
    title="YouTube Summary API",
    description="YouTube動画のメタデータと文字起こしを取得するためのAPIです。",
    version="1.1.0",
)

# --- APIルーターの登録 ---
logger.debug("APIルーターを登録します。")
# summary_router.router をアプリケーションに含める
# これにより、/api/v1/summary エンドポイントが利用可能になる
app.include_router(summary_router.router)


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
