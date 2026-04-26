"""tests/test_search_service.py — Phase 3 SS-1〜SS-12

`app.services.youtube_search.search_videos` のサービス層テスト。

契約（design.md §3.5 / tasks.md Phase 3）:
- 常に `SearchResponse` を返す（例外を投げない）
- search.list (100u) → videos.list (1u) → channels.list (1u) を順に呼ぶ
- 各成功時に `quota_tracker.add_units(cost)` を呼ぶ
- 403 quotaExceeded 受信時に `quota_tracker.mark_exhausted("youtube_403")` を呼ぶ
- 上流 429 / 5xx → `ERROR_RATE_LIMITED`、ネットワーク例外 → `ERROR_INTERNAL`

モック対象:
- `app.services.youtube_search._session.get`
- `app.core.quota_tracker.add_units` / `mark_exhausted`
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
import requests

from app.core.constants import (
    ERROR_INTERNAL,
    ERROR_QUOTA_EXCEEDED,
    ERROR_RATE_LIMITED,
    YOUTUBE_API_V3_CHANNELS_URL,
    YOUTUBE_API_V3_SEARCH_MAX_RESULTS,
    YOUTUBE_API_V3_SEARCH_PART,
    YOUTUBE_API_V3_SEARCH_TYPE,
    YOUTUBE_API_V3_SEARCH_URL,
    YOUTUBE_API_V3_VIDEOS_URL,
)
from app.models.schemas import SearchRequest


# --- ヘルパ ---

def _mock_response(status: int, body: dict | None = None, headers: dict | None = None) -> MagicMock:
    """status_code / json() / headers を持つ requests.Response 互換のモック。"""
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = body if body is not None else {}
    resp.headers = headers if headers is not None else {}
    return resp


def _search_item(video_id: str, channel_id: str = "c1", title: str = "動画") -> dict:
    """search.list の items 1 件分。"""
    return {
        "kind": "youtube#searchResult",
        "id": {"kind": "youtube#video", "videoId": video_id},
        "snippet": {
            "publishedAt": "2026-04-01T10:00:00Z",
            "channelId": channel_id,
            "title": title,
            "description": "desc",
            "channelTitle": "ch",
            "thumbnails": {"default": {"url": "http://x/d.jpg"}},
        },
    }


def _video_item(
    video_id: str,
    channel_id: str = "c1",
    view: str | None = "1000",
    like: str | None = "100",
    comment: str | None = "10",
    caption: str = "true",
    duration: str = "PT5M",
    definition: str = "hd",
) -> dict:
    """videos.list の items 1 件分。"""
    statistics: dict = {}
    if view is not None:
        statistics["viewCount"] = view
    if like is not None:
        statistics["likeCount"] = like
    if comment is not None:
        statistics["commentCount"] = comment
    return {
        "id": video_id,
        "snippet": {
            "publishedAt": "2026-04-01T10:00:00Z",
            "channelId": channel_id,
            "channelTitle": "ch",
            "title": f"V {video_id}",
            "description": "desc body",
            "thumbnails": {
                "default": {"url": "http://x/d.jpg"},
                "high": {"url": "http://x/h.jpg"},
            },
            "tags": ["t1"],
            "categoryId": "27",
        },
        "contentDetails": {
            "duration": duration,
            "definition": definition,
            "caption": caption,
        },
        "statistics": statistics,
    }


def _channel_item(
    channel_id: str = "c1",
    view: str = "1000000",
    videos: str = "100",
    subs: str = "5000",
    created: str = "2020-01-01T00:00:00Z",
) -> dict:
    """channels.list の items 1 件分。"""
    return {
        "id": channel_id,
        "snippet": {
            "publishedAt": created,
            "title": f"Ch {channel_id}",
        },
        "statistics": {
            "viewCount": view,
            "subscriberCount": subs,
            "hiddenSubscriberCount": False,
            "videoCount": videos,
        },
    }


def _search_body(items: list[dict], total: int | None = None) -> dict:
    return {
        "kind": "youtube#searchListResponse",
        "pageInfo": {"totalResults": total if total is not None else len(items), "resultsPerPage": 50},
        "items": items,
    }


@pytest.fixture
def mock_quota(monkeypatch):
    """quota_tracker.add_units / mark_exhausted を MagicMock に差し替える。"""
    from app.core import quota_tracker
    mock_add = MagicMock()
    mock_mark = MagicMock()
    monkeypatch.setattr(quota_tracker, "add_units", mock_add)
    monkeypatch.setattr(quota_tracker, "mark_exhausted", mock_mark)
    return mock_add, mock_mark


@pytest.fixture
def mock_session(monkeypatch):
    """app.services.youtube_search._session.get をモックする。"""
    from app.services import youtube_search
    mock_get = MagicMock()
    monkeypatch.setattr(youtube_search._session, "get", mock_get)
    return mock_get


# =============================================
# SS-1: 正常系 — search → videos → channels が順に 1 回ずつ
# =============================================

def test_ss1_happy_path_calls_three_apis_in_order(mock_quota, mock_session):
    mock_session.side_effect = [
        _mock_response(200, _search_body([_search_item("v1"), _search_item("v2")])),
        _mock_response(200, {"items": [_video_item("v1"), _video_item("v2")]}),
        _mock_response(200, {"items": [_channel_item("c1")]}),
    ]
    from app.services.youtube_search import search_videos

    resp = search_videos(SearchRequest(q="test"))

    assert resp.success is True
    assert resp.error_code is None
    assert resp.results is not None
    assert len(resp.results) == 2
    assert resp.returned_count == 2
    assert resp.query == "test"

    # URL 順序の固定
    urls = [c.args[0] for c in mock_session.call_args_list]
    assert urls == [
        YOUTUBE_API_V3_SEARCH_URL,
        YOUTUBE_API_V3_VIDEOS_URL,
        YOUTUBE_API_V3_CHANNELS_URL,
    ]


# =============================================
# SS-2: 重複動画 ID の排除（videos.list の id パラメタが unique）
# =============================================

def test_ss2_video_ids_deduplicated_in_videos_list(mock_quota, mock_session):
    mock_session.side_effect = [
        _mock_response(200, _search_body([
            _search_item("v1"),
            _search_item("v1"),  # 重複
            _search_item("v2"),
        ])),
        _mock_response(200, {"items": [_video_item("v1"), _video_item("v2")]}),
        _mock_response(200, {"items": [_channel_item("c1")]}),
    ]
    from app.services.youtube_search import search_videos

    search_videos(SearchRequest(q="test"))

    videos_call = mock_session.call_args_list[1]
    id_csv = videos_call.kwargs["params"]["id"]
    ids = id_csv.split(",")
    assert len(ids) == len(set(ids)), f"重複 ID が videos.list へ渡された: {ids}"
    assert sorted(ids) == ["v1", "v2"]


# =============================================
# SS-3: 重複チャンネル ID の排除（channels.list の id パラメタが unique）
# =============================================

def test_ss3_channel_ids_deduplicated_in_channels_list(mock_quota, mock_session):
    mock_session.side_effect = [
        _mock_response(200, _search_body([
            _search_item("v1", channel_id="c1"),
            _search_item("v2", channel_id="c2"),
            _search_item("v3", channel_id="c1"),  # 重複チャンネル
        ])),
        _mock_response(200, {"items": [
            _video_item("v1", channel_id="c1"),
            _video_item("v2", channel_id="c2"),
            _video_item("v3", channel_id="c1"),
        ]}),
        _mock_response(200, {"items": [_channel_item("c1"), _channel_item("c2")]}),
    ]
    from app.services.youtube_search import search_videos

    search_videos(SearchRequest(q="test"))

    channels_call = mock_session.call_args_list[2]
    id_csv = channels_call.kwargs["params"]["id"]
    ids = id_csv.split(",")
    assert len(ids) == len(set(ids)), f"重複 ID が channels.list へ渡された: {ids}"
    assert sorted(ids) == ["c1", "c2"]


# =============================================
# SS-4: 派生値計算 — like_view_ratio = like / view、分母 0 で None
# =============================================

def test_ss4_like_view_ratio_calculation(mock_quota, mock_session):
    mock_session.side_effect = [
        _mock_response(200, _search_body([_search_item("v1")])),
        _mock_response(200, {"items": [_video_item("v1", view="100000", like="5000")]}),
        _mock_response(200, {"items": [_channel_item("c1")]}),
    ]
    from app.services.youtube_search import search_videos

    resp = search_videos(SearchRequest(q="test"))
    assert resp.results is not None
    assert resp.results[0].like_view_ratio == pytest.approx(0.05)


def test_ss4_like_view_ratio_zero_view_returns_none(mock_quota, mock_session):
    mock_session.side_effect = [
        _mock_response(200, _search_body([_search_item("v1")])),
        _mock_response(200, {"items": [_video_item("v1", view="0", like="0")]}),
        _mock_response(200, {"items": [_channel_item("c1")]}),
    ]
    from app.services.youtube_search import search_videos

    resp = search_videos(SearchRequest(q="test"))
    assert resp.results is not None
    assert resp.results[0].like_view_ratio is None


# =============================================
# SS-5: comment_view_ratio + channel_avg_views
# =============================================

def test_ss5_comment_view_ratio_and_channel_avg_views(mock_quota, mock_session):
    mock_session.side_effect = [
        _mock_response(200, _search_body([_search_item("v1")])),
        _mock_response(200, {"items": [_video_item("v1", view="200", comment="10")]}),
        _mock_response(200, {"items": [_channel_item("c1", view="1000000", videos="100")]}),
    ]
    from app.services.youtube_search import search_videos

    resp = search_videos(SearchRequest(q="test"))
    assert resp.results is not None
    r = resp.results[0]
    assert r.comment_view_ratio == pytest.approx(0.05)
    # channel_avg_views = 1_000_000 / 100 = 10_000
    assert r.channel_avg_views == 10000


def test_ss5_channel_avg_views_zero_videos_returns_none(mock_quota, mock_session):
    mock_session.side_effect = [
        _mock_response(200, _search_body([_search_item("v1")])),
        _mock_response(200, {"items": [_video_item("v1")]}),
        _mock_response(200, {"items": [_channel_item("c1", view="1000", videos="0")]}),
    ]
    from app.services.youtube_search import search_videos

    resp = search_videos(SearchRequest(q="test"))
    assert resp.results is not None
    assert resp.results[0].channel_avg_views is None


# =============================================
# SS-6: has_caption — "true" / "false" / 欠損で bool 化
# =============================================

@pytest.mark.parametrize("caption_value, expected", [
    ("true", True),
    ("false", False),
])
def test_ss6_has_caption_bool_conversion(mock_quota, mock_session, caption_value, expected):
    mock_session.side_effect = [
        _mock_response(200, _search_body([_search_item("v1")])),
        _mock_response(200, {"items": [_video_item("v1", caption=caption_value)]}),
        _mock_response(200, {"items": [_channel_item("c1")]}),
    ]
    from app.services.youtube_search import search_videos

    resp = search_videos(SearchRequest(q="test"))
    assert resp.results is not None
    assert resp.results[0].has_caption is expected


def test_ss6_has_caption_missing_defaults_false(mock_quota, mock_session):
    """contentDetails.caption フィールド欠損で False。"""
    video = _video_item("v1")
    del video["contentDetails"]["caption"]
    mock_session.side_effect = [
        _mock_response(200, _search_body([_search_item("v1")])),
        _mock_response(200, {"items": [video]}),
        _mock_response(200, {"items": [_channel_item("c1")]}),
    ]
    from app.services.youtube_search import search_videos

    resp = search_videos(SearchRequest(q="test"))
    assert resp.results is not None
    assert resp.results[0].has_caption is False


# =============================================
# SS-7: 403 quotaExceeded → ERROR_QUOTA_EXCEEDED + mark_exhausted 呼び出し
# =============================================

def test_ss7_403_quota_exceeded_returns_quota_error_and_marks_exhausted(mock_quota, mock_session):
    add_units, mark_exhausted = mock_quota
    body = {
        "error": {
            "code": 403,
            "message": "Quota exceeded.",
            "errors": [{"reason": "quotaExceeded"}],
        }
    }
    mock_session.return_value = _mock_response(403, body)

    from app.services.youtube_search import search_videos
    resp = search_videos(SearchRequest(q="test"))

    assert resp.success is False
    assert resp.error_code == ERROR_QUOTA_EXCEEDED
    assert resp.results is None
    mark_exhausted.assert_called_once_with("youtube_403")
    # search.list 段階で 403 のため、add_units はゼロ回
    add_units.assert_not_called()


# =============================================
# SS-8: 上流 429（リトライ枯渇後）→ ERROR_RATE_LIMITED + retry_after
# =============================================

def test_ss8_upstream_429_returns_rate_limited_with_retry_after(mock_quota, mock_session):
    mock_session.return_value = _mock_response(
        429, {"error": {"code": 429}}, headers={"Retry-After": "120"}
    )
    from app.services.youtube_search import search_videos
    resp = search_videos(SearchRequest(q="test"))

    assert resp.success is False
    assert resp.error_code == ERROR_RATE_LIMITED
    assert resp.results is None
    assert resp.retry_after == 120


def test_ss8_upstream_429_without_retry_after_header_returns_none(mock_quota, mock_session):
    mock_session.return_value = _mock_response(429, {"error": {"code": 429}})
    from app.services.youtube_search import search_videos
    resp = search_videos(SearchRequest(q="test"))

    assert resp.error_code == ERROR_RATE_LIMITED
    assert resp.retry_after is None


# =============================================
# SS-9: 上流 5xx（リトライ枯渇後）→ ERROR_RATE_LIMITED
# =============================================

@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_ss9_upstream_5xx_returns_rate_limited(mock_quota, mock_session, status):
    mock_session.return_value = _mock_response(status, {"error": {"code": status}})
    from app.services.youtube_search import search_videos
    resp = search_videos(SearchRequest(q="test"))

    assert resp.success is False
    assert resp.error_code == ERROR_RATE_LIMITED


# =============================================
# SS-10: ネットワーク例外 → ERROR_INTERNAL
# =============================================

def test_ss10_network_exception_returns_internal(mock_quota, mock_session):
    mock_session.side_effect = requests.RequestException("network down")
    from app.services.youtube_search import search_videos
    resp = search_videos(SearchRequest(q="test"))

    assert resp.success is False
    assert resp.error_code == ERROR_INTERNAL
    assert resp.results is None


# =============================================
# SS-11: add_units が 100 → 1 → 1 の順で 3 回呼ばれる（成功時）
# =============================================

def test_ss11_add_units_called_in_order_for_success_path(mock_quota, mock_session):
    add_units, _ = mock_quota
    mock_session.side_effect = [
        _mock_response(200, _search_body([_search_item("v1")])),
        _mock_response(200, {"items": [_video_item("v1")]}),
        _mock_response(200, {"items": [_channel_item("c1")]}),
    ]
    from app.services.youtube_search import search_videos

    search_videos(SearchRequest(q="test"))

    costs = [c.args[0] for c in add_units.call_args_list]
    assert costs == [100, 1, 1]


def test_ss11_add_units_zero_when_search_list_fails(mock_quota, mock_session):
    """search.list 段階で失敗 → add_units は呼ばれない。"""
    add_units, _ = mock_quota
    mock_session.return_value = _mock_response(503, {"error": {"code": 503}})

    from app.services.youtube_search import search_videos
    search_videos(SearchRequest(q="test"))
    add_units.assert_not_called()


def test_ss11_add_units_partial_when_videos_list_fails(mock_quota, mock_session):
    """search.list 成功 → videos.list 失敗 → add_units(100) のみ。"""
    add_units, _ = mock_quota
    mock_session.side_effect = [
        _mock_response(200, _search_body([_search_item("v1")])),
        _mock_response(503, {"error": {"code": 503}}),
    ]
    from app.services.youtube_search import search_videos

    search_videos(SearchRequest(q="test"))
    costs = [c.args[0] for c in add_units.call_args_list]
    assert costs == [100]


# =============================================
# SS-12: フィルタパラメタが正しく URL クエリにマップされる
# =============================================

def test_ss12_filter_params_mapped_to_search_url(mock_quota, mock_session):
    """snake_case フィールド → camelCase クエリ、type/maxResults 固定、
    publishedAfter/Before は RFC 3339 UTC 文字列に正規化される。"""
    mock_session.side_effect = [
        _mock_response(200, _search_body([])),
    ]
    from app.services.youtube_search import search_videos
    req = SearchRequest(
        q="検索 クエリ",
        order="date",
        published_after=datetime(2026, 1, 1, 9, 0, 0, tzinfo=timezone(timedelta(hours=9))),
        published_before=datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc),
        video_duration="long",
        region_code="JP",
        relevance_language="ja",
        channel_id="UCxxx",
    )
    search_videos(req)

    call = mock_session.call_args_list[0]
    assert call.args[0] == YOUTUBE_API_V3_SEARCH_URL
    params = call.kwargs["params"]

    # 必須/固定パラメタ
    assert params["q"] == "検索 クエリ"
    assert params["type"] == YOUTUBE_API_V3_SEARCH_TYPE
    assert params["maxResults"] == YOUTUBE_API_V3_SEARCH_MAX_RESULTS
    assert params["part"] == YOUTUBE_API_V3_SEARCH_PART

    # snake → camelCase の写像
    assert params["order"] == "date"
    assert params["videoDuration"] == "long"
    assert params["regionCode"] == "JP"
    assert params["relevanceLanguage"] == "ja"
    assert params["channelId"] == "UCxxx"

    # publishedAfter/Before は RFC 3339 UTC 文字列に正規化される
    # JST 09:00 == UTC 00:00
    assert params["publishedAfter"] == "2026-01-01T00:00:00Z"
    assert params["publishedBefore"] == "2026-04-01T00:00:00Z"

    # 受け入れ基準 #4: videoEmbeddable / safeSearch は明示的に送らない
    assert "videoEmbeddable" not in params
    assert "safeSearch" not in params


# =============================================
# 防御的型チェック（専門家レビュー追加分）
# 200 OK でも JSON decode 失敗 / 非 dict body / 不正形状 items は
# ERROR_INTERNAL に倒し、`SearchResponse` を必ず返す（例外を投げない）。
# 契約参照: design.md §3.5「常に SearchResponse を返す」 + 要件 #11 INTERNAL_ERROR。
# =============================================

def _bad_json_response() -> MagicMock:
    """200 OK だが response.json() が ValueError を投げる Response モック。"""
    bad = MagicMock()
    bad.status_code = 200
    bad.json.side_effect = ValueError("not JSON")
    bad.headers = {}
    return bad


def _non_dict_body_response(value) -> MagicMock:
    """200 OK だが body が dict でない（list / str など）Response モック。"""
    bad = MagicMock()
    bad.status_code = 200
    bad.json.return_value = value
    bad.headers = {}
    return bad


def test_ss_search_list_invalid_json_returns_internal(mock_quota, mock_session):
    """search.list が 200 OK でも JSON decode 失敗 → ERROR_INTERNAL（success=True にしない）。"""
    add_units, _ = mock_quota
    mock_session.return_value = _bad_json_response()

    from app.services.youtube_search import search_videos
    resp = search_videos(SearchRequest(q="test"))

    assert resp.success is False
    assert resp.error_code == ERROR_INTERNAL
    assert resp.results is None
    # 200 でも body が壊れていれば quota 加算しない（責務: 結果を内部で使えないため）
    add_units.assert_not_called()


def test_ss_search_list_non_dict_body_returns_internal(mock_quota, mock_session):
    """search.list が 200 OK で body が dict でない（list）→ ERROR_INTERNAL。"""
    mock_session.return_value = _non_dict_body_response(["not", "a", "dict"])

    from app.services.youtube_search import search_videos
    resp = search_videos(SearchRequest(q="test"))

    assert resp.success is False
    assert resp.error_code == ERROR_INTERNAL


def test_ss_search_list_items_not_list_returns_internal(mock_quota, mock_session):
    """body.items が list でない（文字列）→ ERROR_INTERNAL。"""
    mock_session.return_value = _mock_response(200, {"items": "not-a-list"})

    from app.services.youtube_search import search_videos
    resp = search_videos(SearchRequest(q="test"))

    assert resp.success is False
    assert resp.error_code == ERROR_INTERNAL


def test_ss_search_list_item_not_dict_returns_internal(mock_quota, mock_session):
    """items 内に dict でない要素を含む → ERROR_INTERNAL。"""
    mock_session.return_value = _mock_response(
        200, {"items": [_search_item("v1"), "not-a-dict"]}
    )

    from app.services.youtube_search import search_videos
    resp = search_videos(SearchRequest(q="test"))

    assert resp.success is False
    assert resp.error_code == ERROR_INTERNAL


def test_ss_search_list_non_dict_pageinfo_handled_gracefully(mock_quota, mock_session):
    """pageInfo が dict でない場合は total_results_estimate=None で **緩く** 成功扱いとする。

    pageInfo は派生メタ情報で必須ではないため、欠損や壊れた型は致命扱いせず
    「items が空 → success=True / returned_count=0」として返す。
    """
    mock_session.return_value = _mock_response(
        200, {"items": [], "pageInfo": "broken"}
    )

    from app.services.youtube_search import search_videos
    resp = search_videos(SearchRequest(q="test"))

    assert resp.success is True
    assert resp.error_code is None
    assert resp.total_results_estimate is None
    assert resp.returned_count == 0


def test_ss_videos_list_non_dict_body_returns_internal(mock_quota, mock_session):
    """videos.list が 200 OK で body が dict でない → ERROR_INTERNAL。"""
    add_units, _ = mock_quota
    mock_session.side_effect = [
        _mock_response(200, _search_body([_search_item("v1")])),
        _non_dict_body_response("broken"),
    ]
    from app.services.youtube_search import search_videos
    resp = search_videos(SearchRequest(q="test"))

    assert resp.success is False
    assert resp.error_code == ERROR_INTERNAL
    # search.list 段階の add_units(100) は積まれている
    costs = [c.args[0] for c in add_units.call_args_list]
    assert costs == [100]


def test_ss_channels_list_invalid_json_returns_internal(mock_quota, mock_session):
    """channels.list が 200 OK で JSON decode 失敗 → ERROR_INTERNAL。"""
    add_units, _ = mock_quota
    mock_session.side_effect = [
        _mock_response(200, _search_body([_search_item("v1")])),
        _mock_response(200, {"items": [_video_item("v1")]}),
        _bad_json_response(),
    ]
    from app.services.youtube_search import search_videos
    resp = search_videos(SearchRequest(q="test"))

    assert resp.success is False
    assert resp.error_code == ERROR_INTERNAL
    # search.list + videos.list は加算済み
    costs = [c.args[0] for c in add_units.call_args_list]
    assert costs == [100, 1]


def test_ss_videos_list_items_not_list_returns_internal(mock_quota, mock_session):
    """videos.list の body.items が list でない → ERROR_INTERNAL。"""
    mock_session.side_effect = [
        _mock_response(200, _search_body([_search_item("v1")])),
        _mock_response(200, {"items": "broken"}),
    ]
    from app.services.youtube_search import search_videos
    resp = search_videos(SearchRequest(q="test"))

    assert resp.success is False
    assert resp.error_code == ERROR_INTERNAL


def test_ss_search_list_search_item_id_not_dict_returns_internal(mock_quota, mock_session):
    """item の `id` フィールドが dict でない（文字列）→ ERROR_INTERNAL。"""
    bad_item = {
        "kind": "youtube#searchResult",
        "id": "not-a-dict",  # YouTube 仕様では {"kind","videoId"} の dict
        "snippet": {"channelId": "c1"},
    }
    mock_session.return_value = _mock_response(200, {"items": [bad_item]})

    from app.services.youtube_search import search_videos
    resp = search_videos(SearchRequest(q="test"))

    assert resp.success is False
    assert resp.error_code == ERROR_INTERNAL
