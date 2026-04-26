# app/routers/search.py

"""POST /api/v1/search エンドポイント。

設計参照: design.md §3.6 / §6.2、tasks.md Phase 4。

責務:
1. 認証通過後の **全結果** を `quota_tracker.record_api_call(endpoint='search', ...)` で
   `api_calls` に 1 行記録する（受け入れ基準 #15）
2. 各レスポンス（200 / 429 / 503 / 500）に `quota` を **frozen=True 経由の `model_copy`** で同梱する
3. HTTP ステータスを正規化する（FR-5）:
   - 成功 → 200
   - クライアント側レート制限 → 429 + `Retry-After`
   - 推定クォータ枯渇 / YouTube 403 quotaExceeded → 429 + `Retry-After`
   - YouTube 5xx / 429 リトライ枯渇 → 503 + `Retry-After`
   - 内部例外 → 500
4. 認証エラー（401）は `verify_api_key_for_search` が `HTTPException(detail=dict)` を
   投げる。本 router は到達せず、main.py のグローバル `HTTPException` ハンドラが整形する
"""

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.core import async_rate_limiter, quota_tracker
from app.core.constants import (
    ERROR_CLIENT_RATE_LIMITED,
    ERROR_INTERNAL,
    ERROR_QUOTA_EXCEEDED,
    ERROR_RATE_LIMITED,
    MSG_INTERNAL_ERROR,
    MSG_QUOTA_EXCEEDED_TEMPLATE,
)
from app.core.security import verify_api_key_for_search
from app.models.schemas import SearchRequest, SearchResponse
from app.services.youtube_search import search_videos

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Search"])


def _map_to_http(response: SearchResponse) -> tuple[int, dict[str, str]]:
    """SearchResponse の error_code を HTTP ステータス + ヘッダにマップする。"""
    code = response.error_code
    if code is None:
        return 200, {}
    if code == ERROR_CLIENT_RATE_LIMITED:
        retry = response.retry_after if response.retry_after is not None else 1
        return 429, {"Retry-After": str(retry)}
    if code == ERROR_QUOTA_EXCEEDED:
        snap = quota_tracker.get_snapshot()
        return 429, {"Retry-After": str(snap.reset_in_seconds)}
    if code == ERROR_RATE_LIMITED:
        if response.retry_after is not None:
            return 503, {"Retry-After": str(response.retry_after)}
        return 503, {}
    if code == ERROR_INTERNAL:
        return 500, {}
    # 未知の error_code は内部エラー扱い（保険）
    return 500, {}


@router.post("/search")
async def search(
    body: SearchRequest,
    _: str = Depends(verify_api_key_for_search),
):
    """YouTube 検索エンドポイント。

    `verify_api_key_for_search` を通過した時点で **全結果を `api_calls` に記録**する
    （受け入れ基準 #15）。`quota` は frozen な `SearchResponse` に対して
    `model_copy(update={"quota": ...})` で注入する。
    """
    # ContextVar をリクエスト先頭で必ずリセット（並行リクエスト間で last_call_cost が混ざらないようにする）
    quota_tracker.reset_request_cost()

    response: SearchResponse | None = None
    http_status: int = 500
    headers: dict[str, str] = {}

    try:
        # 1) クライアント側レート制限（API 未呼び出し）
        allowed, blocked = await async_rate_limiter.check_request()
        if not allowed:
            response = SearchResponse(
                success=False,
                message=blocked["message"],
                error_code=ERROR_CLIENT_RATE_LIMITED,
                query=body.q,
                retry_after=blocked["retry_after"],
            )
            http_status, headers = _map_to_http(response)

        # 2) 推定クォータ枯渇（API 未呼び出し）
        elif quota_tracker.is_exhausted():
            snap = quota_tracker.get_snapshot()
            response = SearchResponse(
                success=False,
                message=MSG_QUOTA_EXCEEDED_TEMPLATE.format(
                    daily_limit=snap.daily_limit,
                    reset_in_seconds=snap.reset_in_seconds,
                    reset_jst=snap.reset_at_jst.isoformat(),
                ),
                error_code=ERROR_QUOTA_EXCEEDED,
                query=body.q,
                retry_after=snap.reset_in_seconds,
            )
            http_status = 429
            headers = {"Retry-After": str(snap.reset_in_seconds)}

        # 3) サービス層（成功・失敗どちらも SearchResponse を返す契約）
        else:
            # 注: `asyncio.to_thread` は context を **コピー** して実行するため、
            # 別スレッドで `quota_tracker.add_units` が ContextVar (`_request_cost`)
            # に書き込んでも router 側コルーチンには伝播せず `last_call_cost` が 0 のまま
            # になる。本サーバは単一プロセス・単一ワーカ運用 (FR-7) で /search の
            # 想定 latency も短いため、サービス層を **同コルーチン上で同期呼び出し** する
            # （イベントループは一時的にブロックされるが、ContextVar 整合を優先）。
            response = search_videos(body)

            # service がリトライ枯渇後の 429 / 5xx を ERROR_RATE_LIMITED で返すとき、
            # Retry-After ヘッダ値は service が response.retry_after に格納している
            http_status, headers = _map_to_http(response)

    except Exception:  # noqa: BLE001 — router 最終セーフティネット
        logger.exception("/search router で予期せぬ例外")
        response = SearchResponse(
            success=False,
            message=MSG_INTERNAL_ERROR,
            error_code=ERROR_INTERNAL,
            query=body.q,
        )
        http_status = 500
        headers = {}

    finally:
        # 認証通過後の全結果を 1 行記録 + quota 同梱（response が None になる経路は無いが念のため）
        if response is not None:
            snap = quota_tracker.get_snapshot()
            response = response.model_copy(update={"quota": snap})
            try:
                quota_tracker.record_api_call(
                    endpoint="search",
                    input_summary=body.q,
                    units_cost=quota_tracker.get_request_cost(),
                    http_status=http_status,
                    http_success=(200 <= http_status < 300),
                    error_code=response.error_code,
                    transcript_success=None,
                    transcript_language=None,
                    result_count=response.returned_count,
                )
            except Exception:  # noqa: BLE001
                logger.exception("/search の api_calls 記録に失敗")

    assert response is not None  # 上の try/except で必ず代入される
    return JSONResponse(
        content=response.model_dump(mode="json"),
        status_code=http_status,
        headers=headers,
    )
