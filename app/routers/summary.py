# app/routers/summary.py

"""
このモジュールは、動画要約機能に関連するAPIエンドポイントを定義します。
"""

import logging

from fastapi import APIRouter, Depends

# --- アプリケーション内モジュールのインポート ---
from app.models.schemas import VideoRequest, SummaryResponse
from app.services.youtube import get_summary_data
from app.core.security import verify_api_key
from app.core.rate_limiter import check_request

# このモジュール用のロガーを設定
logger = logging.getLogger(__name__)

# APIRouterインスタンスを作成
router = APIRouter(
    prefix="/api/v1",
    tags=["Summary"],
)


@router.post("/summary", response_model=SummaryResponse)
async def get_summary(request: VideoRequest, _: str = Depends(verify_api_key)):
    """
    YouTube動画のURLを受け取り、動画のメタデータと文字起こしを返します。
    
    サービス層(`app.services.youtube`)がビジネスロジックを担当し、
    成功・失敗にかかわらず、常に`SummaryResponse`形式で結果を返します。

    - **request**: `VideoRequest`モデル。`url`キーにYouTubeのURLを含むJSON。
    - **return**: `SummaryResponse`モデル。処理結果と動画情報を含むJSON。
    """
    video_url = str(request.url)
    logger.info(f"APIリクエスト受信: {video_url}")

    # クライアント側レート制限チェック (YouTubeへの集中アクセスを予防)
    allowed, blocked = check_request()
    if not allowed:
        logger.warning(
            f"レート制限により拒否: retry_after={blocked['retry_after']}s | URL: {video_url}"
        )
        return SummaryResponse(success=False, **blocked)

    # サービス層の関数を呼び出し、結果をそのまま返す
    # エラーハンドリングはサービス層に集約されている
    response_data = get_summary_data(video_url=video_url)
    
    if response_data.success:
        logger.info(f"処理成功: {response_data.title}")
    else:
        logger.warning(f"処理失敗: {response_data.message} | URL: {video_url}")

    return response_data


