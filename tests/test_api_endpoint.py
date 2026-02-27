"""テストケース E-1〜E-7: APIエンドポイントの統合テスト"""

from unittest.mock import MagicMock, patch

from app.core.constants import (
    ERROR_INVALID_URL,
    ERROR_TRANSCRIPT_NOT_FOUND,
)


ENDPOINT = "/api/v1/summary"
VALID_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def _resp(status_code: int, payload: dict):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


def _make_v3_api_mock(mock_get, video_response: dict, channel_response: dict | None = None):
    side_effects = [_resp(200, video_response)]
    if channel_response is not None:
        side_effects.append(_resp(200, channel_response))
    mock_get.side_effect = side_effects


def _make_transcript_mock(mock_ytt_class, language_code="ja", is_generated=False):
    mock_ytt = mock_ytt_class.return_value
    mock_fetched = MagicMock()
    mock_fetched.language_code = language_code
    mock_fetched.is_generated = is_generated
    mock_fetched.to_raw_data.return_value = [
        {"text": "こんにちは", "start": 0.0, "duration": 1.5},
    ]
    mock_ytt.fetch.return_value = mock_fetched


V3_VIDEO_RESPONSE = {
    "items": [{
        "snippet": {
            "title": "統合テスト動画",
            "channelTitle": "統合テストチャンネル",
            "channelId": "UCtest",
            "publishedAt": "2026-02-10T00:00:00Z",
            "description": "統合テスト",
            "thumbnails": {
                "maxres": {"url": "https://i.ytimg.com/vi/test/maxresdefault.jpg"},
            },
            "tags": ["test"],
            "categoryId": "28",
        },
        "contentDetails": {"duration": "PT2M"},
        "statistics": {"viewCount": "1000", "likeCount": "50"},
    }]
}

V3_CHANNEL_RESPONSE = {
    "items": [{
        "statistics": {
            "subscriberCount": "100",
            "hiddenSubscriberCount": False,
        }
    }]
}


# --- E-1: 正常リクエスト ---

@patch("app.services.youtube.requests.get")
@patch("app.services.youtube.YouTubeTranscriptApi")
def test_e1_success(mock_ytt_class, mock_get, client):
    """POST /api/v1/summary → 200, 全フィールド存在"""
    _make_v3_api_mock(mock_get, V3_VIDEO_RESPONSE, V3_CHANNEL_RESPONSE)
    _make_transcript_mock(mock_ytt_class)

    resp = client.post(ENDPOINT, json={"url": VALID_URL})

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["status"] == "ok"
    assert data["message"] == "Successfully retrieved data."
    assert data["error_code"] is None
    assert data["title"] == "統合テスト動画"
    assert data["channel_name"] == "統合テストチャンネル"
    assert data["upload_date"] == "2026-02-10"
    assert data["duration"] == 120
    assert data["duration_string"] == "2:00"
    assert data["view_count"] == 1000
    assert data["like_count"] == 50
    assert data["thumbnail_url"] == "https://i.ytimg.com/vi/test/maxresdefault.jpg"
    assert data["description"] == "統合テスト"
    assert data["tags"] == ["test"]
    assert data["categories"] == ["Science & Technology"]
    assert data["channel_id"] == "UCtest"
    assert data["channel_follower_count"] == 100
    assert data["webpage_url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert data["transcript"] is not None
    assert data["transcript_language"] == "ja"
    assert data["is_generated"] is False


# --- E-2: APIキーなし ---

def test_e2_no_api_key(client_no_auth_override):
    """POST → 403"""
    resp = client_no_auth_override.post(ENDPOINT, json={"url": VALID_URL})
    assert resp.status_code == 403


# --- E-3: 無効なURL ---

def test_e3_invalid_url(client):
    """POST → 200, success=False, error_code=INVALID_URL"""
    resp = client.post(ENDPOINT, json={"url": "https://example.com/not-youtube"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert data["error_code"] == ERROR_INVALID_URL


# --- E-4: 字幕なし動画 ---

@patch("app.services.youtube.requests.get")
@patch("app.services.youtube.YouTubeTranscriptApi")
def test_e4_no_transcript(mock_ytt_class, mock_get, client):
    """POST → 200, success=False, error_code=TRANSCRIPT_NOT_FOUND, メタデータあり"""
    from youtube_transcript_api import NoTranscriptFound

    _make_v3_api_mock(mock_get, V3_VIDEO_RESPONSE, V3_CHANNEL_RESPONSE)
    mock_ytt = mock_ytt_class.return_value
    mock_ytt.fetch.side_effect = NoTranscriptFound("dQw4w9WgXcQ", ["ja", "en"], {})

    resp = client.post(ENDPOINT, json={"url": VALID_URL})

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert data["error_code"] == ERROR_TRANSCRIPT_NOT_FOUND
    assert data["title"] == "統合テスト動画"
    assert data["transcript"] is None


# --- E-5: 後方互換性 ---

@patch("app.services.youtube.requests.get")
@patch("app.services.youtube.YouTubeTranscriptApi")
def test_e5_backward_compatibility(mock_ytt_class, mock_get, client):
    """レスポンスJSONに既存5フィールドが含まれ、型が正しい"""
    _make_v3_api_mock(mock_get, V3_VIDEO_RESPONSE, V3_CHANNEL_RESPONSE)
    _make_transcript_mock(mock_ytt_class)

    resp = client.post(ENDPOINT, json={"url": VALID_URL})
    data = resp.json()

    assert isinstance(data["success"], bool)
    assert isinstance(data["message"], str)
    assert isinstance(data["title"], str)
    assert isinstance(data["channel_name"], str)
    assert isinstance(data["transcript"], str)


# --- E-6: status フィールド ---

@patch("app.services.youtube.requests.get")
@patch("app.services.youtube.YouTubeTranscriptApi")
def test_e6_status_field(mock_ytt_class, mock_get, client):
    """成功時 status='ok'、失敗時 status='error'"""
    from youtube_transcript_api import NoTranscriptFound

    mock_get.side_effect = [
        _resp(200, V3_VIDEO_RESPONSE),
        _resp(200, V3_CHANNEL_RESPONSE),
        _resp(200, V3_VIDEO_RESPONSE),
        _resp(200, V3_CHANNEL_RESPONSE),
    ]

    _make_transcript_mock(mock_ytt_class)
    resp_ok = client.post(ENDPOINT, json={"url": VALID_URL})
    assert resp_ok.json()["status"] == "ok"

    mock_ytt = mock_ytt_class.return_value
    mock_ytt.fetch.side_effect = NoTranscriptFound("dQw4w9WgXcQ", ["ja", "en"], {})
    resp_err = client.post(ENDPOINT, json={"url": VALID_URL})
    assert resp_err.json()["status"] == "error"


# --- E-7: transcript_language, is_generated がレスポンスに含まれる ---

@patch("app.services.youtube.requests.get")
@patch("app.services.youtube.YouTubeTranscriptApi")
def test_e7_transcript_metadata_in_response(mock_ytt_class, mock_get, client):
    """成功時に transcript_language と is_generated が設定されている"""
    _make_v3_api_mock(mock_get, V3_VIDEO_RESPONSE, V3_CHANNEL_RESPONSE)
    _make_transcript_mock(mock_ytt_class, language_code="en", is_generated=True)

    resp = client.post(ENDPOINT, json={"url": VALID_URL})
    data = resp.json()

    assert data["transcript_language"] == "en"
    assert data["is_generated"] is True
