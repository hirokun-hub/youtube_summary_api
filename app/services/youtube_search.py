# app/services/youtube_search.py

"""YouTube Data API v3 の search.list を中心とした検索サービス。

設計参照: design.md §3.5 / tasks.md Phase 3。

契約:
- 公開関数 `search_videos(req)` は **常に `SearchResponse` を返す**（例外を投げない）
- search.list (100u) → videos.list (1u) → channels.list (1u) を順に呼ぶ
- 各成功時に `quota_tracker.add_units(cost)` を呼ぶ
- 403 quotaExceeded 受信時に `quota_tracker.mark_exhausted("youtube_403")` を呼ぶ
- リトライ枯渇後の 429 / 5xx → `ERROR_RATE_LIMITED`（router 側で HTTP 503）
- 403 quotaExceeded → `ERROR_QUOTA_EXCEEDED`（router 側で HTTP 429）
- ネットワーク例外 → `ERROR_INTERNAL`

実装上の注意:
- HTTP は `requests.Session` + `urllib3.util.retry.Retry` を使う
- `raise_on_status=False` を必須とする（リトライ枯渇後も最終 HTTP レスポンスを
  そのまま受け取り、戻り値で error_code を確定するため）
- 既存 `_call_youtube_api_with_retry` / `_classify_api_error` は **再利用しない**
  （`/summary` 互換のため 403 quotaExceeded → RATE_LIMITED 固定になっているが、
   `/search` では QUOTA_EXCEEDED と RATE_LIMITED を区別する必要があるため）
- `_parse_iso8601_duration` / `_format_duration_string` / `_select_best_thumbnail`
  / `_to_int_or_none` / `_extract_api_error_reason` は `app.services.youtube` から再利用
"""

import logging
import os
from datetime import timezone
from itertools import batched

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.core import quota_tracker
from app.core.constants import (
    ERROR_INTERNAL,
    ERROR_QUOTA_EXCEEDED,
    ERROR_RATE_LIMITED,
    QUOTA_COST_CHANNELS_LIST,
    QUOTA_COST_SEARCH_LIST,
    QUOTA_COST_VIDEOS_LIST,
    YOUTUBE_API_V3_CHANNELS_BATCH_SIZE,
    YOUTUBE_API_V3_CHANNELS_PART,
    YOUTUBE_API_V3_CHANNELS_URL,
    YOUTUBE_API_V3_MAX_RETRIES,
    YOUTUBE_API_V3_SEARCH_MAX_RESULTS,
    YOUTUBE_API_V3_SEARCH_PART,
    YOUTUBE_API_V3_SEARCH_TYPE,
    YOUTUBE_API_V3_SEARCH_URL,
    YOUTUBE_API_V3_TIMEOUT,
    YOUTUBE_API_V3_VIDEOS_BATCH_SIZE,
    YOUTUBE_API_V3_VIDEOS_PART,
    YOUTUBE_API_V3_VIDEOS_URL,
    YOUTUBE_CATEGORY_MAP,
    YOUTUBE_WATCH_URL_TEMPLATE,
)
from app.models.schemas import SearchRequest, SearchResponse, SearchResult
from app.services.youtube import (
    _extract_api_error_reason,
    _format_duration_string,
    _parse_iso8601_duration,
    _select_best_thumbnail,
    _to_int_or_none,
)

logger = logging.getLogger(__name__)


# --- 内部メッセージ（AI/LLM Tool 消費前提のため英語固定） ---
_MSG_SUCCESS = "Successfully retrieved search results."
_MSG_QUOTA_EXCEEDED = "YouTube Data API daily quota exhausted."
_MSG_RATE_LIMITED = "YouTube Data API is currently rate-limiting requests; retry later."
_MSG_INTERNAL = "Internal error while calling YouTube Data API."

_YT_REASON_QUOTA_EXCEEDED = "quotaExceeded"


# --- HTTP セッション（モジュール単一インスタンス） ---
# raise_on_status=False が必須: リトライ枯渇後に urllib3 が MaxRetryError を投げると
# 「常に SearchResponse を返す（例外を投げない）」契約が壊れる。最終 HTTP レスポンス
# を受け取って _classify_search_api_error で正規化する設計。
_session = requests.Session()
_retry = Retry(
    total=YOUTUBE_API_V3_MAX_RETRIES,
    status_forcelist=[429, 500, 502, 503, 504],
    backoff_factor=1.0,
    backoff_jitter=0.3,
    respect_retry_after_header=True,
    allowed_methods=["GET"],
    raise_on_status=False,
)
_session.mount("https://", HTTPAdapter(max_retries=_retry))


def _classify_search_api_error(status_code: int, error_body: dict | None) -> str:
    """/search 専用の YouTube API エラー分類。

    マッピング:
      - 403 quotaExceeded     → ERROR_QUOTA_EXCEEDED
      - 429（リトライ枯渇後） → ERROR_RATE_LIMITED
      - 5xx（リトライ枯渇後） → ERROR_RATE_LIMITED
      - その他 4xx            → ERROR_INTERNAL
    """
    reason = _extract_api_error_reason(error_body)
    if status_code == 403 and reason == _YT_REASON_QUOTA_EXCEEDED:
        return ERROR_QUOTA_EXCEEDED
    if status_code == 429 or 500 <= status_code < 600:
        return ERROR_RATE_LIMITED
    return ERROR_INTERNAL


def _compute_ratio(numerator: int | None, denominator: int | None) -> float | None:
    """divisor が 0 / None なら None。それ以外は numer/denom を float で返す。"""
    if numerator is None or not denominator:
        return None
    return numerator / denominator


def _parse_caption(value: str | None) -> bool:
    """contentDetails.caption の "true"/"false"/None を bool に。"""
    if value is None:
        return False
    return str(value).lower() == "true"


def _retry_after_from_headers(headers: dict | None) -> int | None:
    """Retry-After ヘッダ値を秒単位の int として取得。なければ None。"""
    if not headers:
        return None
    raw = headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _format_rfc3339_utc(dt) -> str:
    """timezone-aware datetime を RFC 3339 (UTC, 'Z' 表記) に変換する。"""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_search_params(req: SearchRequest, api_key: str) -> dict:
    """search.list 用 query parameters を組み立てる（snake → camelCase）。"""
    params: dict = {
        "part": YOUTUBE_API_V3_SEARCH_PART,
        "type": YOUTUBE_API_V3_SEARCH_TYPE,
        "maxResults": YOUTUBE_API_V3_SEARCH_MAX_RESULTS,
        "q": req.q,
        "key": api_key,
    }
    if req.order is not None:
        params["order"] = req.order
    if req.video_duration is not None:
        params["videoDuration"] = req.video_duration
    if req.region_code is not None:
        params["regionCode"] = req.region_code
    if req.relevance_language is not None:
        params["relevanceLanguage"] = req.relevance_language
    if req.channel_id is not None:
        params["channelId"] = req.channel_id
    if req.published_after is not None:
        params["publishedAfter"] = _format_rfc3339_utc(req.published_after)
    if req.published_before is not None:
        params["publishedBefore"] = _format_rfc3339_utc(req.published_before)
    return params


def _call_api(url: str, params: dict) -> tuple[int, dict | None, dict, str | None]:
    """単発の YouTube API HTTP コール。

    戻り値: (status_code, body_or_none, headers_dict, error_code_or_none)
      - 成功 (200): (200, body, headers, None)
      - HTTP エラー: (status, body_or_none, headers, error_code)
      - ネットワーク例外: (0, None, {}, ERROR_INTERNAL)
    """
    try:
        response = _session.get(url, params=params, timeout=YOUTUBE_API_V3_TIMEOUT)
    except requests.RequestException:
        logger.warning("youtube_search: network error", exc_info=True)
        return 0, None, {}, ERROR_INTERNAL

    body: dict | None
    try:
        body = response.json()
    except ValueError:
        body = None

    headers = dict(response.headers) if getattr(response, "headers", None) else {}

    if response.status_code == 200:
        # 200 OK でも JSON decode 失敗、または body が dict でない場合は上流契約違反。
        # 「常に SearchResponse を返す」契約を守るため ERROR_INTERNAL に倒す。
        if not isinstance(body, dict):
            logger.warning(
                "youtube_search: 200 response body is not a dict (decode failed or non-dict JSON)"
            )
            return 200, None, headers, ERROR_INTERNAL
        return 200, body, headers, None

    error_code = _classify_search_api_error(response.status_code, body)
    return response.status_code, body, headers, error_code


def _safe_items(body: dict | None) -> list[dict] | None:
    """body から `items` を取り出し、list[dict] か None を返す。

    - body が dict でない、items が list でない、要素に dict 以外を含む → None
      （上流契約違反のシグナル。呼び出し側で ERROR_INTERNAL に倒す）
    - items キー不在 / None → 空 list（YouTube API 通常応答での 0 件ヒット相当）
    """
    if not isinstance(body, dict):
        return None
    items = body.get("items")
    if items is None:
        return []
    if not isinstance(items, list):
        return None
    if not all(isinstance(it, dict) for it in items):
        return None
    return items


def _failure_response(
    error_code: str, query: str, retry_after: int | None = None
) -> SearchResponse:
    """サービス層の失敗時 SearchResponse を組み立てる。"""
    msg_map = {
        ERROR_QUOTA_EXCEEDED: _MSG_QUOTA_EXCEEDED,
        ERROR_RATE_LIMITED: _MSG_RATE_LIMITED,
        ERROR_INTERNAL: _MSG_INTERNAL,
    }
    return SearchResponse(
        success=False,
        message=msg_map.get(error_code, _MSG_INTERNAL),
        error_code=error_code,
        query=query,
        retry_after=retry_after,
    )


def _handle_call_error(
    error_code: str, headers: dict, query: str
) -> SearchResponse:
    """API コール失敗時の共通後処理: 必要なら mark_exhausted を呼んで失敗 response を返す。"""
    if error_code == ERROR_QUOTA_EXCEEDED:
        quota_tracker.mark_exhausted("youtube_403")
    retry_after = (
        _retry_after_from_headers(headers) if error_code == ERROR_RATE_LIMITED else None
    )
    return _failure_response(error_code, query, retry_after)


def _build_search_result(video_item: dict, channels_by_id: dict[str, dict]) -> SearchResult:
    """videos.list 1 件と channels.list dict から SearchResult を組み立てる。"""
    snippet = video_item.get("snippet") or {}
    content_details = video_item.get("contentDetails") or {}
    statistics = video_item.get("statistics") or {}

    channel_id = snippet.get("channelId") or ""
    channel_item = channels_by_id.get(channel_id) or {}
    ch_snippet = channel_item.get("snippet") or {}
    ch_stats = channel_item.get("statistics") or {}

    duration_seconds = _parse_iso8601_duration(content_details.get("duration"))

    category_id = snippet.get("categoryId")
    category = (
        YOUTUBE_CATEGORY_MAP.get(category_id, category_id) if category_id else None
    )

    view_count = _to_int_or_none(statistics.get("viewCount"))
    like_count = _to_int_or_none(statistics.get("likeCount"))
    comment_count = _to_int_or_none(statistics.get("commentCount"))

    channel_video_count = _to_int_or_none(ch_stats.get("videoCount"))
    channel_total_view_count = _to_int_or_none(ch_stats.get("viewCount"))

    # subscriberCount が hidden の場合は None を返す
    channel_follower_count = None
    if ch_stats.get("hiddenSubscriberCount") is not True:
        channel_follower_count = _to_int_or_none(ch_stats.get("subscriberCount"))

    channel_avg_views: int | None = None
    if (
        channel_video_count is not None
        and channel_video_count > 0
        and channel_total_view_count is not None
    ):
        channel_avg_views = channel_total_view_count // channel_video_count

    upload_date: str | None = None
    pa = snippet.get("publishedAt")
    if isinstance(pa, str) and len(pa) >= 10:
        upload_date = pa[:10]

    channel_created_at: str | None = None
    cpa = ch_snippet.get("publishedAt")
    if isinstance(cpa, str) and len(cpa) >= 10:
        channel_created_at = cpa[:10]

    video_id = video_item.get("id") or ""

    return SearchResult(
        video_id=video_id,
        title=snippet.get("title") or "",
        channel_name=snippet.get("channelTitle") or "",
        channel_id=channel_id,
        upload_date=upload_date,
        thumbnail_url=_select_best_thumbnail(snippet.get("thumbnails")),
        webpage_url=YOUTUBE_WATCH_URL_TEMPLATE.format(video_id=video_id),
        description=snippet.get("description") or "",
        tags=snippet.get("tags"),
        category=category,
        duration=duration_seconds,
        duration_string=_format_duration_string(duration_seconds),
        has_caption=_parse_caption(content_details.get("caption")),
        definition=content_details.get("definition"),
        view_count=view_count,
        like_count=like_count,
        like_view_ratio=_compute_ratio(like_count, view_count),
        comment_count=comment_count,
        comment_view_ratio=_compute_ratio(comment_count, view_count),
        channel_follower_count=channel_follower_count,
        channel_video_count=channel_video_count,
        channel_total_view_count=channel_total_view_count,
        channel_created_at=channel_created_at,
        channel_avg_views=channel_avg_views,
    )


def search_videos(req: SearchRequest) -> SearchResponse:
    """検索エントリポイント。常に `SearchResponse` を返す（例外を投げない）。

    `_do_search` 本体は予期せぬ例外を投げ得る（_build_search_result 内の不正型など）が、
    本関数で必ず捕捉して ERROR_INTERNAL の SearchResponse に倒す。これにより
    router 側の最終セーフティネットが発火しなくても契約を守れる。
    """
    try:
        return _do_search(req)
    except Exception:
        logger.exception("youtube_search: 予期せぬ例外（search_videos 内最終捕捉）")
        return _failure_response(ERROR_INTERNAL, req.q)


def _do_search(req: SearchRequest) -> SearchResponse:
    """search_videos の実装本体。

    フロー:
      1. search.list — 失敗時はその時点で SearchResponse(success=False)
      2. videos.list（重複 videoId 排除済み、バッチ）
      3. channels.list（重複 channelId 排除済み、バッチ）
      4. 結合 + 派生値計算 + has_caption 設定 → SearchResponse(success=True)
    """
    api_key = os.getenv("YOUTUBE_API_KEY") or ""

    # --- 1) search.list ---
    status, body, headers, err = _call_api(
        YOUTUBE_API_V3_SEARCH_URL, _build_search_params(req, api_key)
    )
    if err is not None:
        return _handle_call_error(err, headers, req.q)
    quota_tracker.add_units(QUOTA_COST_SEARCH_LIST)

    # 防御的: items / pageInfo の型を検証（200 OK でも YouTube が壊れた形状を返す可能性）
    items = _safe_items(body)
    if items is None:
        logger.warning("youtube_search: search.list の items 形状が不正")
        return _failure_response(ERROR_INTERNAL, req.q)

    page_info = body.get("pageInfo") if isinstance(body, dict) else None
    total_results_estimate = (
        page_info.get("totalResults") if isinstance(page_info, dict) else None
    )

    # videoId を順序保ちつつ unique 化（item.id は dict 形状を要求）
    video_ids: list[str] = []
    seen_v: set[str] = set()
    for it in items:
        vid_obj = it.get("id")
        if vid_obj is not None and not isinstance(vid_obj, dict):
            logger.warning("youtube_search: search.list item の id が dict でない")
            return _failure_response(ERROR_INTERNAL, req.q)
        vid = vid_obj.get("videoId") if isinstance(vid_obj, dict) else None
        if not vid or vid in seen_v:
            continue
        seen_v.add(vid)
        video_ids.append(vid)

    if not video_ids:
        # 検索ヒット 0 件: videos / channels は呼ばずに success=True で返す
        return SearchResponse(
            success=True,
            message=_MSG_SUCCESS,
            error_code=None,
            query=req.q,
            total_results_estimate=total_results_estimate,
            returned_count=0,
            results=[],
        )

    # --- 2) videos.list（バッチ） ---
    videos_by_id: dict[str, dict] = {}
    for batch in batched(video_ids, YOUTUBE_API_V3_VIDEOS_BATCH_SIZE):
        status, body, headers, err = _call_api(
            YOUTUBE_API_V3_VIDEOS_URL,
            {
                "part": YOUTUBE_API_V3_VIDEOS_PART,
                "id": ",".join(batch),
                "key": api_key,
            },
        )
        if err is not None:
            return _handle_call_error(err, headers, req.q)
        quota_tracker.add_units(QUOTA_COST_VIDEOS_LIST)

        videos_items = _safe_items(body)
        if videos_items is None:
            logger.warning("youtube_search: videos.list の items 形状が不正")
            return _failure_response(ERROR_INTERNAL, req.q)
        for v in videos_items:
            vid = v.get("id")
            if isinstance(vid, str) and vid:
                videos_by_id[vid] = v

    # --- 3) channels.list（バッチ） ---
    channel_ids: list[str] = []
    seen_c: set[str] = set()
    for vid in video_ids:
        v = videos_by_id.get(vid)
        if not v:
            continue
        snippet = v.get("snippet") if isinstance(v, dict) else None
        cid = snippet.get("channelId") if isinstance(snippet, dict) else None
        if cid and cid not in seen_c:
            seen_c.add(cid)
            channel_ids.append(cid)

    channels_by_id: dict[str, dict] = {}
    if channel_ids:
        for batch in batched(channel_ids, YOUTUBE_API_V3_CHANNELS_BATCH_SIZE):
            status, body, headers, err = _call_api(
                YOUTUBE_API_V3_CHANNELS_URL,
                {
                    "part": YOUTUBE_API_V3_CHANNELS_PART,
                    "id": ",".join(batch),
                    "key": api_key,
                },
            )
            if err is not None:
                return _handle_call_error(err, headers, req.q)
            quota_tracker.add_units(QUOTA_COST_CHANNELS_LIST)

            channels_items = _safe_items(body)
            if channels_items is None:
                logger.warning("youtube_search: channels.list の items 形状が不正")
                return _failure_response(ERROR_INTERNAL, req.q)
            for c in channels_items:
                cid = c.get("id")
                if isinstance(cid, str) and cid:
                    channels_by_id[cid] = c

    # --- 4) 結合 ---
    results: list[SearchResult] = []
    for vid in video_ids:
        v = videos_by_id.get(vid)
        if v is None:
            # 削除/非公開の動画: search.list には出るが videos.list には現れない
            continue
        results.append(_build_search_result(v, channels_by_id))

    return SearchResponse(
        success=True,
        message=_MSG_SUCCESS,
        error_code=None,
        query=req.q,
        total_results_estimate=total_results_estimate,
        returned_count=len(results),
        results=results,
    )
