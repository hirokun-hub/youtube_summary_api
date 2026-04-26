# app/routers/summary.py

"""POST /api/v1/summary エンドポイント。

設計参照: design.md §3.7、tasks.md Phase 5。

Phase 5 改修内容:
- レスポンスに `quota` を 3 経路（rate limit 早期 / 通常完了 / サービス層失敗）すべてで同梱する
- 認証通過後の **全結果** を `quota_tracker.record_api_call(endpoint='summary', ...)` で
  `api_calls` に 1 行記録する（受け入れ基準 #15）
- HTTP は **200 固定**（既存挙動維持、TC-9 / iPhone ショートカット後方互換）
- `last_call_cost` は ContextVar 経由でリクエストローカルに集計（並行リクエストの干渉を排除）
"""

import logging

from fastapi import APIRouter, Depends

# --- アプリケーション内モジュールのインポート ---
from app.models.schemas import VideoRequest, SummaryResponse
from app.services.youtube import get_summary_data, _extract_video_id
from app.core import quota_tracker
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

    # 並行リクエスト間で last_call_cost が混ざらないよう、リクエスト先頭で必ず ContextVar をリセット
    quota_tracker.reset_request_cost()

    response: SummaryResponse | None = None

    try:
        # 経路 1: クライアント側レート制限 — 早期 return（API 未呼び出し）
        allowed, blocked = check_request()
        if not allowed:
            logger.warning(
                f"レート制限により拒否: retry_after={blocked['retry_after']}s | URL: {video_url}"
            )
            response = SummaryResponse(success=False, **blocked)
        else:
            # 経路 2/3: サービス層（成功・失敗どちらも SummaryResponse を返す）
            response = get_summary_data(video_url=video_url)

            if response.success:
                logger.info(f"処理成功: {response.title}")
            else:
                logger.warning(
                    f"処理失敗: {response.message} | URL: {video_url}"
                )
    finally:
        # 認証通過後の全結果に quota を同梱 + api_calls に 1 行記録
        if response is not None:
            snap = quota_tracker.get_snapshot()
            # SummaryResponse は frozen ではないが、/search と同じイディオムで一貫性を保つ
            response = response.model_copy(update={"quota": snap})
            try:
                # requirements.md L387 / design.md L1046: input_summary は "q or video_id"。
                # 抽出失敗（INVALID_URL ケース）では原 URL を fallback として記録する。
                video_id = _extract_video_id(video_url)
                input_summary = video_id or video_url
                quota_tracker.record_api_call(
                    endpoint="summary",
                    input_summary=input_summary,
                    units_cost=quota_tracker.get_request_cost(),
                    http_status=200,  # /summary は 200 固定
                    http_success=response.success,
                    error_code=response.error_code,
                    transcript_success=(response.transcript is not None),
                    transcript_language=response.transcript_language,
                    result_count=None,
                )
            except Exception:  # noqa: BLE001
                # quota_tracker が未 init の環境（lifespan を回さない TestClient 等）でも
                # 既存挙動を破壊しないよう、記録失敗は warning に倒す
                logger.warning(
                    "/summary の api_calls 記録に失敗（quota_tracker 未 init の可能性）",
                    exc_info=True,
                )

    return response
