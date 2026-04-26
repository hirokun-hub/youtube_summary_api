"""tests/test_summary_quota_injection.py — Phase 5 SU-1〜SU-5

`POST /api/v1/summary` に `quota` を 3 経路で同梱し、認証通過後の
**全結果** を `api_calls` に 1 行記録することを検証する（受け入れ基準 #8 / #15 / #17）。

検証経路:
- 経路1: 通常完了（success） — videos.list 1 + channels.list 1 = 2 units
- 経路2: rate limit 早期 return — API 未呼び出し（last_call_cost == 0）
- 経路3: サービス層失敗（VIDEO_NOT_FOUND） — videos.list のみ呼ばれた段階での失敗

`/summary` は HTTP 200 固定（iPhone ショートカット後方互換、TC-9）。
"""

from unittest.mock import MagicMock, patch

import pytest

from app.core import quota_tracker
from app.core.constants import (
    ERROR_CLIENT_RATE_LIMITED,
    ERROR_VIDEO_NOT_FOUND,
)


ENDPOINT = "/api/v1/summary"
VALID_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


# --- 共通ヘルパ ---

def _resp(status_code: int, payload: dict, headers: dict | None = None):
    """requests.get のモック応答を作成する。"""
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    response.headers = headers or {}
    return response


def _count_api_calls(db_path) -> int:
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute("SELECT COUNT(*) FROM api_calls").fetchone()[0]
    finally:
        conn.close()


def _last_api_call(db_path) -> dict:
    """最新の api_calls 行を dict で返す（行が無ければ AssertionError）。"""
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


# --- 固定レスポンスデータ（test_api_endpoint.py と独立、Phase 5 専用に最低限）---

V3_VIDEO_RESPONSE = {
    "items": [{
        "snippet": {
            "title": "SU テスト動画",
            "channelTitle": "SU テストチャンネル",
            "channelId": "UCsutest",
            "publishedAt": "2026-02-10T00:00:00Z",
            "description": "Phase 5 SU テスト",
            "thumbnails": {
                "high": {"url": "https://i.ytimg.com/vi/test/hqdefault.jpg"},
            },
            "tags": ["su"],
            "categoryId": "27",
        },
        "contentDetails": {"duration": "PT3M"},
        "statistics": {"viewCount": "100", "likeCount": "10"},
    }]
}

V3_CHANNEL_RESPONSE = {
    "items": [{
        "snippet": {"publishedAt": "2020-01-01T00:00:00Z", "title": "Ch"},
        "statistics": {
            "subscriberCount": "1000",
            "hiddenSubscriberCount": False,
        },
    }]
}


# --- fixtures ---

@pytest.fixture
def usage_db_path(tmp_path):
    """quota_tracker を tmp_path/usage.db で再 init する（履歴記録の検証用）。

    TestClient は lifespan を再実行しないため、手動で init して DB パスを差し替える。
    teardown では reset() してプロセス内状態をクリアする。
    """
    db_path = tmp_path / "usage.db"
    quota_tracker.reset()
    quota_tracker.init(db_path)
    yield db_path
    quota_tracker.reset()


def _make_transcript_mock(mock_ytt_class, language_code="ja", is_generated=False):
    mock_ytt = mock_ytt_class.return_value
    mock_fetched = MagicMock()
    mock_fetched.language_code = language_code
    mock_fetched.is_generated = is_generated
    mock_fetched.to_raw_data.return_value = [
        {"text": "テスト", "start": 0.0, "duration": 1.0},
    ]
    mock_ytt.fetch.return_value = mock_fetched


# =============================================
# SU-1: 正常完了 → quota.last_call_cost == 2 + api_calls 1 行
# =============================================

@patch("app.services.youtube.requests.get")
@patch("app.services.youtube.YouTubeTranscriptApi")
def test_su1_summary_response_has_quota_and_recorded(
    mock_ytt_class, mock_get, client, usage_db_path
):
    """成功時: videos.list 1 + channels.list 1 = 2 units、api_calls に 1 行。"""
    pre_consumed = quota_tracker.get_snapshot().consumed_units_today

    mock_get.side_effect = [
        _resp(200, V3_VIDEO_RESPONSE),
        _resp(200, V3_CHANNEL_RESPONSE),
    ]
    _make_transcript_mock(mock_ytt_class)

    resp = client.post(ENDPOINT, json={"url": VALID_URL})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["error_code"] is None

    # quota 同梱検証
    quota = body["quota"]
    assert quota is not None, f"quota が None: {body}"
    assert quota["last_call_cost"] == 2, f"last_call_cost={quota['last_call_cost']}"
    assert quota["consumed_units_today"] == pre_consumed + 2
    assert quota["daily_limit"] == 10_000

    # api_calls 1 行 INSERT 検証
    assert _count_api_calls(usage_db_path) == 1
    row = _last_api_call(usage_db_path)
    assert row["endpoint"] == "summary"
    assert row["units_cost"] == 2
    assert row["http_status"] == 200
    assert row["http_success"] == 1
    assert row["error_code"] is None
    assert row["transcript_success"] == 1
    assert row["transcript_language"] == "ja"
    assert row["result_count"] is None  # /summary は result_count なし


# =============================================
# SU-2: 既存 success=True レスポンスに quota が常に含まれる
# =============================================

@patch("app.services.youtube.requests.get")
@patch("app.services.youtube.YouTubeTranscriptApi")
def test_su2_summary_success_always_has_quota(
    mock_ytt_class, mock_get, client, usage_db_path
):
    """成功レスポンスに `quota` キーが必ず存在する（既存 22 フィールド + quota）。"""
    mock_get.side_effect = [
        _resp(200, V3_VIDEO_RESPONSE),
        _resp(200, V3_CHANNEL_RESPONSE),
    ]
    _make_transcript_mock(mock_ytt_class)

    resp = client.post(ENDPOINT, json={"url": VALID_URL})
    body = resp.json()
    assert "quota" in body, f"レスポンスに quota キーが無い: {list(body.keys())}"
    assert body["quota"] is not None
    assert body["quota"]["daily_limit"] == 10_000


# =============================================
# SU-3: HTTP 200 固定（既存挙動を維持、エラー時も 200）
# =============================================

@patch("app.services.youtube.requests.get")
@patch("app.services.youtube.YouTubeTranscriptApi")
def test_su3_summary_http_status_always_200(
    mock_ytt_class, mock_get, client, usage_db_path
):
    """字幕取得失敗（TRANSCRIPT_NOT_FOUND）でも HTTP 200 を維持する。"""
    from youtube_transcript_api import NoTranscriptFound

    mock_get.side_effect = [
        _resp(200, V3_VIDEO_RESPONSE),
        _resp(200, V3_CHANNEL_RESPONSE),
    ]
    mock_ytt = mock_ytt_class.return_value
    mock_ytt.fetch.side_effect = NoTranscriptFound("dQw4w9WgXcQ", ["ja", "en"], {})

    resp = client.post(ENDPOINT, json={"url": VALID_URL})
    assert resp.status_code == 200, f"/summary は失敗時も 200 固定: {resp.status_code}"
    body = resp.json()
    assert body["success"] is False
    # エラー時も quota は付く（業務処理を通ったため）
    assert body["quota"] is not None


# =============================================
# SU-4: rate limit 早期 return → quota.last_call_cost == 0 + api_calls 1 行
# =============================================

def test_su4_summary_rate_limited_has_quota_and_recorded(
    client, usage_db_path, monkeypatch
):
    """check_request が拒否を返す経路でも quota 同梱 + api_calls 記録される。"""
    # router 内で `from app.core.rate_limiter import check_request` で参照しているため、
    # router の名前空間の参照を直接差し替える必要がある
    def fake_check_request():
        return (
            False,
            {
                "error_code": ERROR_CLIENT_RATE_LIMITED,
                "message": "リクエスト間隔が短すぎます。30秒後に再試行してください。",
                "retry_after": 30,
            },
        )

    monkeypatch.setattr(
        "app.routers.summary.check_request", fake_check_request
    )

    resp = client.post(ENDPOINT, json={"url": VALID_URL})
    assert resp.status_code == 200  # /summary は 200 固定
    body = resp.json()
    assert body["success"] is False
    assert body["error_code"] == ERROR_CLIENT_RATE_LIMITED
    assert body["retry_after"] == 30

    # quota 同梱（API 未呼び出しのため last_call_cost == 0）
    assert body["quota"] is not None
    assert body["quota"]["last_call_cost"] == 0

    # api_calls 1 行 INSERT
    assert _count_api_calls(usage_db_path) == 1
    row = _last_api_call(usage_db_path)
    assert row["endpoint"] == "summary"
    assert row["units_cost"] == 0
    assert row["http_status"] == 200  # /summary は 200 固定
    assert row["http_success"] == 0
    assert row["error_code"] == ERROR_CLIENT_RATE_LIMITED


# =============================================
# SU-5: VIDEO_NOT_FOUND → quota.last_call_cost == 1 + api_calls 1 行
# =============================================

@patch("app.services.youtube.requests.get")
def test_su5_summary_service_failure_has_quota_and_recorded(
    mock_get, client, usage_db_path
):
    """videos.list 200 + items=[] → VIDEO_NOT_FOUND 早期 return。

    videos.list は呼ばれた（200）→ add_units(1) 計上、channels.list は呼ばれない。
    last_call_cost == 1 が記録される。transcript も到達せず None。
    """
    mock_get.side_effect = [_resp(200, {"items": []})]

    resp = client.post(ENDPOINT, json={"url": VALID_URL})
    assert resp.status_code == 200  # /summary は 200 固定
    body = resp.json()
    assert body["success"] is False
    assert body["error_code"] == ERROR_VIDEO_NOT_FOUND

    # quota 同梱（videos.list の 1 unit のみ）
    assert body["quota"] is not None
    assert body["quota"]["last_call_cost"] == 1

    # api_calls 1 行
    assert _count_api_calls(usage_db_path) == 1
    row = _last_api_call(usage_db_path)
    assert row["endpoint"] == "summary"
    assert row["units_cost"] == 1
    assert row["error_code"] == ERROR_VIDEO_NOT_FOUND
    assert row["http_status"] == 200
    assert row["http_success"] == 0
    # transcript 未到達のため transcript_success=False (0)
    assert row["transcript_success"] == 0
    assert row["transcript_language"] is None
