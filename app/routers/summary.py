# app/routers/summary.py

"""
このモジュールは、動画要約機能に関連するAPIエンドポイントを定義します。
"""

import logging
import urllib.error
from requests.exceptions import HTTPError as RequestsHTTPError

from fastapi import APIRouter, Depends, HTTPException
from youtube_transcript_api import NoTranscriptFound

# --- アプリケーション内モジュールのインポート ---
from app.models.schemas import VideoRequest, VideoResponse
from app.services.youtube import get_video_details
from app.core.security import verify_api_key

# このモジュール用のロガーを設定
logger = logging.getLogger(__name__)

# APIRouterインスタンスを作成
# これにより、このファイル内のエンドポイントを後でメインのFastAPIアプリに結合できる
router = APIRouter(
    prefix="/api/v1",  # このルーターの全エンドポイントに共通のパスプレフィックス
    tags=["Summary"],  # Swagger UIでのグルーピング用タグ
)


@router.post("/summary", response_model=VideoResponse)
async def get_summary(request: VideoRequest, _: str = Depends(verify_api_key)):
    """
    YouTube動画のURLを受け取り、動画のメタデータと文字起こしを返します。
    ビジネスロジックはサービス層 (app.services.youtube) に委譲します。

    - **request**: `VideoRequest`モデル。`url`キーにYouTubeのURLを含むJSON。
    - **return**: `VideoResponse`モデル。動画情報を含むJSON。
    """
    video_url = str(request.url)
    logger.info(f"APIリクエスト受信: {video_url}")
    try:
        # サービス層の関数を呼び出して、ビジネスロジックを実行
        response_data = get_video_details(video_url=video_url)
        logger.info(f"処理成功: {response_data.title}")
        return response_data

    except NoTranscriptFound:
        logger.warning(f"文字起こしが見つかりませんでした: {video_url}")
        raise HTTPException(status_code=404, detail="この動画には利用可能な文字起こしがありません。")
    
    except (urllib.error.HTTPError, RequestsHTTPError) as http_err:
        logger.warning(f"YouTube / oEmbed API から HTTPError が返されました: {http_err}")
        # エラーレスポンスからステータスコードを慎重に抽出
        status_code = getattr(http_err, 'code', None)
        if status_code is None and hasattr(http_err, 'response') and http_err.response is not None:
            status_code = http_err.response.status_code
        # ステータスコードが取得できない場合は、汎用的な400エラーとする
        final_status = status_code or 400
        raise HTTPException(status_code=final_status, detail=f"YouTube から {final_status} エラーが返されました。動画が存在しないか、制限されている可能性があります。")

    except ValueError as ve:
        # サービス層で発生したバリデーションエラーや、その他のハンドリングされたエラー
        logger.warning(f"入力値または処理中にエラーが発生: {ve} | URL: {video_url}")
        raise HTTPException(status_code=400, detail=str(ve))

    except Exception as e:
        # 予期せぬサーバー内部のエラー
        logger.error(f"ルーター層で予期せぬエラーが発生しました: {video_url}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部サーバーエラーが発生しました。")
