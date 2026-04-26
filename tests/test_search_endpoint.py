"""tests/test_search_endpoint.py — Phase 4 ST-1〜ST-9

`POST /api/v1/search` の router 統合テスト。

検証観点:
- 認証通過 / バリデーション / レート制限早期 return / クォータ枯渇早期 return /
  サービス層失敗 / 内部例外 の各経路で HTTP ステータス・本文・ヘッダを固定する
- 認証通過後の **全結果** が `api_calls` に 1 行 INSERT される（受け入れ基準 #15）
- 401 / 422 では `quota` フィールドを **含めない**、それ以外では含める

モック対象:
- `app.services.youtube_search._session.get` — YouTube 3 段 API
- `app.core.async_rate_limiter.check_request` — レート制限拒否シナリオ
- `app.core.quota_tracker.is_exhausted` — クォータ枯渇シナリオ
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core import async_rate_limiter, quota_tracker
from app.core.constants import (
    ERROR_CLIENT_RATE_LIMITED,
    ERROR_INTERNAL,
    ERROR_QUOTA_EXCEEDED,
    ERROR_RATE_LIMITED,
    ERROR_UNAUTHORIZED,
    YOUTUBE_API_V3_CHANNELS_URL,
    YOUTUBE_API_V3_SEARCH_URL,
    YOUTUBE_API_V3_VIDEOS_URL,
)
from app.core.security import verify_api_key_for_search
from main import app

ENDPOINT = "/api/v1/search"
AUTH_HEADERS = {"X-API-KEY": "test-api-key"}


# --- 共通ヘルパ ---

def _mock_response(status: int, body: dict | None = None, headers: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = body if body is not None else {}
    resp.headers = headers if headers is not None else {}
    return resp


def _search_item(video_id: str, channel_id: str = "c1") -> dict:
    return {
        "id": {"kind": "youtube#video", "videoId": video_id},
        "snippet": {
            "publishedAt": "2026-04-01T10:00:00Z",
            "channelId": channel_id,
            "title": f"動画 {video_id}",
            "description": "desc",
            "channelTitle": "ch",
            "thumbnails": {"default": {"url": "http://x/d.jpg"}},
        },
    }


def _video_item(video_id: str, channel_id: str = "c1") -> dict:
    return {
        "id": video_id,
        "snippet": {
            "publishedAt": "2026-04-01T10:00:00Z",
            "channelId": channel_id,
            "channelTitle": "ch",
            "title": f"V {video_id}",
            "description": "body",
            "thumbnails": {"default": {"url": "http://x/d.jpg"}},
            "tags": ["t"],
            "categoryId": "27",
        },
        "contentDetails": {"duration": "PT5M", "definition": "hd", "caption": "true"},
        "statistics": {"viewCount": "1000", "likeCount": "100", "commentCount": "10"},
    }


def _channel_item(channel_id: str = "c1") -> dict:
    return {
        "id": channel_id,
        "snippet": {"publishedAt": "2020-01-01T00:00:00Z", "title": "Ch"},
        "statistics": {
            "viewCount": "1000000",
            "subscriberCount": "5000",
            "hiddenSubscriberCount": False,
            "videoCount": "100",
        },
    }


def _search_body(items: list[dict]) -> dict:
    return {
        "kind": "youtube#searchListResponse",
        "pageInfo": {"totalResults": len(items), "resultsPerPage": 50},
        "items": items,
    }


def _count_api_calls(db_path) -> int:
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute("SELECT COUNT(*) FROM api_calls").fetchone()[0]
    finally:
        conn.close()


def _last_api_call(db_path) -> dict:
    """最新の api_calls 行を dict で返す（行が無ければ KeyError 相当の空 dict は返さず例外）。"""
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM api_calls ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            raise AssertionError("api_calls に行が無い")
        return dict(row)
    finally:
        conn.close()


# --- fixtures ---

@pytest.fixture(autouse=True)
def _reset_search_rate_limiter():
    """各テスト前後に /search 用 async レート制限器の deque / lock をリセットする。"""
    async_rate_limiter.reset()
    yield
    async_rate_limiter.reset()


@pytest.fixture
def usage_db_path(tmp_path):
    """quota_tracker を tmp_path/usage.db で再 init する（履歴記録の検証に使う）。

    TestClient は lifespan を再実行しないため、手動で init して DB パスを差し替える。
    teardown では reset() してプロセス内状態をクリアする。
    """
    db_path = tmp_path / "usage.db"
    quota_tracker.reset()
    quota_tracker.init(db_path)
    yield db_path
    quota_tracker.reset()


@pytest.fixture
def mock_session(monkeypatch):
    """app.services.youtube_search._session.get をモック。"""
    from app.services import youtube_search
    mock_get = MagicMock()
    monkeypatch.setattr(youtube_search._session, "get", mock_get)
    return mock_get


@pytest.fixture
def client():
    """`verify_api_key_for_search` をバイパスする TestClient。

    `.env.local` がロードされた状態の `API_KEY` 値を毎回モックヘッダで合わせる代わりに、
    依存性を上書きすることで「認証通過後の挙動」を素直にテストできる。401 を検証する
    ST-2 では `unauth_client`（上書き無し）を別途使う。
    """
    app.dependency_overrides[verify_api_key_for_search] = lambda: "test-key"
    yield TestClient(app)
    app.dependency_overrides.pop(verify_api_key_for_search, None)


@pytest.fixture
def unauth_client():
    """依存性上書きなしの TestClient（401 検証用）。"""
    app.dependency_overrides.pop(verify_api_key_for_search, None)
    yield TestClient(app)
    app.dependency_overrides.pop(verify_api_key_for_search, None)


# =============================================
# ST-1: 正常リクエスト 200 + quota 同梱 + api_calls 1 行
# =============================================

def test_st1_success_200_with_quota_and_recorded(usage_db_path, mock_session, client):
    pre_consumed = quota_tracker.get_snapshot().consumed_units_today

    mock_session.side_effect = [
        _mock_response(200, _search_body([_search_item("v1"), _search_item("v2")])),
        _mock_response(200, {"items": [_video_item("v1"), _video_item("v2")]}),
        _mock_response(200, {"items": [_channel_item("c1")]}),
    ]

    resp = client.post(ENDPOINT, json={"q": "テスト"}, headers=AUTH_HEADERS)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["error_code"] is None
    assert body["returned_count"] == 2
    assert body["query"] == "テスト"

    # quota 同梱（last_call_cost == 102, consumed == pre + 102）
    quota = body["quota"]
    assert quota is not None
    assert quota["last_call_cost"] == 102
    assert quota["consumed_units_today"] == pre_consumed + 102
    assert quota["daily_limit"] == 10_000
    assert quota["remaining_units_estimate"] == 10_000 - (pre_consumed + 102)

    # api_calls に 1 行 INSERT
    assert _count_api_calls(usage_db_path) == 1
    row = _last_api_call(usage_db_path)
    assert row["endpoint"] == "search"
    assert row["units_cost"] == 102
    assert row["http_status"] == 200
    assert row["http_success"] == 1
    assert row["error_code"] is None
    assert row["result_count"] == 2


# =============================================
# ST-2: X-API-KEY 欠落 → 401 + quota 無し + api_calls 行追加なし
# =============================================

def test_st2_unauthorized_401_no_quota_no_record(usage_db_path, unauth_client):
    resp = unauth_client.post(ENDPOINT, json={"q": "x"})  # ヘッダなし
    assert resp.status_code == 401
    body = resp.json()
    assert body["error_code"] == ERROR_UNAUTHORIZED
    assert body["success"] is False
    assert "quota" not in body, f"401 で quota が含まれてはならない: {body}"

    assert _count_api_calls(usage_db_path) == 0


# =============================================
# ST-3: q 未指定 → 422、detail のみ、api_calls 行追加なし
# =============================================

def test_st3_q_missing_422_no_quota_no_record(usage_db_path, client):
    resp = client.post(ENDPOINT, json={}, headers=AUTH_HEADERS)
    assert resp.status_code == 422
    body = resp.json()
    assert "detail" in body
    assert "quota" not in body
    assert "success" not in body  # FastAPI 標準形式
    assert "error_code" not in body

    assert _count_api_calls(usage_db_path) == 0


# =============================================
# ST-4: order 列挙外 → 422、api_calls 行追加なし
# =============================================

def test_st4_order_invalid_422_no_record(usage_db_path, client):
    resp = client.post(
        ENDPOINT, json={"q": "x", "order": "FOO"}, headers=AUTH_HEADERS
    )
    assert resp.status_code == 422
    body = resp.json()
    assert "detail" in body
    assert _count_api_calls(usage_db_path) == 0


# =============================================
# ST-5: レート制限超過 → 429 + Retry-After + quota 同梱 + api_calls 1 行
# =============================================

def test_st5_client_rate_limited_429(usage_db_path, mock_session, client, monkeypatch):
    # check_request を常に拒否させる（11 回目相当）
    async def fake_check_request(now=None):
        return (
            False,
            {
                "error_code": ERROR_CLIENT_RATE_LIMITED,
                "message": (
                    "Search rate limit exceeded: more than 10 requests in the last 60 seconds. "
                    "Rule: max 10 requests per 60 seconds. Retry after 12 seconds."
                ),
                "retry_after": 12,
            },
        )

    monkeypatch.setattr(async_rate_limiter, "check_request", fake_check_request)

    resp = client.post(ENDPOINT, json={"q": "x"}, headers=AUTH_HEADERS)
    assert resp.status_code == 429
    assert resp.headers.get("Retry-After") == "12"
    body = resp.json()
    assert body["success"] is False
    assert body["error_code"] == ERROR_CLIENT_RATE_LIMITED
    assert body["retry_after"] == 12
    assert "max 10 requests per 60 seconds" in body["message"]
    assert "12 seconds" in body["message"]
    assert body["quota"] is not None
    assert body["quota"]["last_call_cost"] == 0  # API 未呼び出し

    # YouTube API は呼ばれない
    assert mock_session.call_count == 0

    # api_calls に記録される（受け入れ基準 #15）
    assert _count_api_calls(usage_db_path) == 1
    row = _last_api_call(usage_db_path)
    assert row["endpoint"] == "search"
    assert row["units_cost"] == 0
    assert row["http_status"] == 429
    assert row["http_success"] == 0
    assert row["error_code"] == ERROR_CLIENT_RATE_LIMITED


# =============================================
# ST-6: クォータ枯渇 → 429 + QUOTA_EXCEEDED + remaining=0 + api_calls 1 行
# =============================================

def test_st6_quota_exhausted_429(usage_db_path, mock_session, client, monkeypatch):
    monkeypatch.setattr(quota_tracker, "is_exhausted", lambda now_utc=None: True)
    # 残量を 0 に見せるため snapshot が読む in-memory カウンタを daily_limit に設定
    quota_tracker._state["consumed_units_today"] = 10_000

    resp = client.post(ENDPOINT, json={"q": "x"}, headers=AUTH_HEADERS)
    assert resp.status_code == 429
    assert resp.headers.get("Retry-After") is not None
    body = resp.json()
    assert body["error_code"] == ERROR_QUOTA_EXCEEDED
    assert body["quota"]["remaining_units_estimate"] == 0

    # YouTube API は呼ばれない
    assert mock_session.call_count == 0

    # 履歴記録
    assert _count_api_calls(usage_db_path) == 1
    row = _last_api_call(usage_db_path)
    assert row["units_cost"] == 0
    assert row["http_status"] == 429
    assert row["error_code"] == ERROR_QUOTA_EXCEEDED


# =============================================
# ST-7: YouTube 403 quotaExceeded → 429 + QUOTA_EXCEEDED + api_calls 1 行
# =============================================

def test_st7_youtube_403_normalized_to_429(usage_db_path, mock_session, client):
    # search.list 段階で 403 quotaExceeded を受信
    quota_error_body = {
        "error": {
            "code": 403,
            "message": "quotaExceeded",
            "errors": [{"reason": "quotaExceeded", "domain": "youtube.quota"}],
        }
    }
    mock_session.side_effect = [_mock_response(403, quota_error_body)]

    resp = client.post(ENDPOINT, json={"q": "x"}, headers=AUTH_HEADERS)
    assert resp.status_code == 429
    body = resp.json()
    assert body["error_code"] == ERROR_QUOTA_EXCEEDED
    assert body["success"] is False

    # api_calls 1 行 — search.list 失敗のため units_cost == 0
    assert _count_api_calls(usage_db_path) == 1
    row = _last_api_call(usage_db_path)
    assert row["units_cost"] == 0
    assert row["error_code"] == ERROR_QUOTA_EXCEEDED


# =============================================
# ST-8: YouTube 429 → 503 + Retry-After + RATE_LIMITED + api_calls 1 行
# =============================================

def test_st8_youtube_429_normalized_to_503(usage_db_path, mock_session, client):
    # urllib3.Retry がリトライ枯渇後に 429 をそのまま返した想定
    mock_session.side_effect = [_mock_response(429, {"error": {"code": 429}}, headers={"Retry-After": "30"})]

    resp = client.post(ENDPOINT, json={"q": "x"}, headers=AUTH_HEADERS)
    assert resp.status_code == 503
    assert resp.headers.get("Retry-After") == "30"
    body = resp.json()
    assert body["error_code"] == ERROR_RATE_LIMITED
    assert body["retry_after"] == 30
    assert body["quota"] is not None

    # 履歴記録
    assert _count_api_calls(usage_db_path) == 1
    row = _last_api_call(usage_db_path)
    assert row["http_status"] == 503
    assert row["error_code"] == ERROR_RATE_LIMITED


# =============================================
# ST-9: 内部例外 → 500 + INTERNAL_ERROR + quota 同梱 + api_calls 1 行
# =============================================

def test_st9_internal_error_500(usage_db_path, mock_session, client, monkeypatch):
    # サービス層が例外を投げる経路を強制（router の except Exception で 500 に倒れる）
    from app.routers import search as search_router

    def boom(req):
        raise RuntimeError("想定外バグ")

    monkeypatch.setattr(search_router, "search_videos", boom)

    resp = client.post(ENDPOINT, json={"q": "x"}, headers=AUTH_HEADERS)
    assert resp.status_code == 500
    body = resp.json()
    assert body["error_code"] == ERROR_INTERNAL
    assert body["success"] is False
    assert body["quota"] is not None

    # 履歴記録
    assert _count_api_calls(usage_db_path) == 1
    row = _last_api_call(usage_db_path)
    assert row["http_status"] == 500
    assert row["error_code"] == ERROR_INTERNAL
