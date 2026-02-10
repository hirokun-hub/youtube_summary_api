"""テストケース E-1〜E-7: APIエンドポイントの統合テスト"""

from unittest.mock import patch, MagicMock

from app.core.constants import (
    ERROR_INVALID_URL,
    ERROR_TRANSCRIPT_NOT_FOUND,
)


ENDPOINT = "/api/v1/summary"
VALID_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def _make_ytdlp_mock(mock_ydl_class, info):
    mock_ydl = mock_ydl_class.return_value.__enter__.return_value
    mock_ydl.extract_info.return_value = info
    mock_ydl.sanitize_info.return_value = info


def _make_transcript_mock(mock_ytt_class, language_code="ja", is_generated=False):
    mock_ytt = mock_ytt_class.return_value
    mock_fetched = MagicMock()
    mock_fetched.language_code = language_code
    mock_fetched.is_generated = is_generated
    mock_fetched.to_raw_data.return_value = [
        {"text": "こんにちは", "start": 0.0, "duration": 1.5},
    ]
    mock_ytt.fetch.return_value = mock_fetched


YTDLP_INFO = {
    "title": "統合テスト動画",
    "channel": "統合テストチャンネル",
    "channel_id": "UCtest",
    "channel_follower_count": 100,
    "upload_date": "20260210",
    "duration": 120,
    "duration_string": "2:00",
    "view_count": 1000,
    "like_count": 50,
    "thumbnail": "https://i.ytimg.com/vi/test/maxresdefault.jpg",
    "description": "統合テスト",
    "tags": ["test"],
    "categories": ["Science"],
    "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
}


# --- E-1: 正常リクエスト ---

@patch("app.services.youtube.YouTubeTranscriptApi")
@patch("app.services.youtube.yt_dlp.YoutubeDL")
def test_e1_success(mock_ydl_class, mock_ytt_class, client):
    """POST /api/v1/summary → 200, 全フィールド存在"""
    _make_ytdlp_mock(mock_ydl_class, YTDLP_INFO)
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
    assert data["upload_date"] == "20260210"
    assert data["duration"] == 120
    assert data["duration_string"] == "2:00"
    assert data["view_count"] == 1000
    assert data["like_count"] == 50
    assert data["thumbnail_url"] == "https://i.ytimg.com/vi/test/maxresdefault.jpg"
    assert data["description"] == "統合テスト"
    assert data["tags"] == ["test"]
    assert data["categories"] == ["Science"]
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

@patch("app.services.youtube.YouTubeTranscriptApi")
@patch("app.services.youtube.yt_dlp.YoutubeDL")
def test_e3_invalid_url(mock_ydl_class, mock_ytt_class, client):
    """POST → 200, success=False, error_code=INVALID_URL"""
    resp = client.post(ENDPOINT, json={"url": "https://example.com/not-youtube"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert data["error_code"] == ERROR_INVALID_URL


# --- E-4: 字幕なし動画 ---

@patch("app.services.youtube.YouTubeTranscriptApi")
@patch("app.services.youtube.yt_dlp.YoutubeDL")
def test_e4_no_transcript(mock_ydl_class, mock_ytt_class, client):
    """POST → 200, success=False, error_code=TRANSCRIPT_NOT_FOUND, メタデータあり"""
    from youtube_transcript_api import NoTranscriptFound

    _make_ytdlp_mock(mock_ydl_class, YTDLP_INFO)
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

@patch("app.services.youtube.YouTubeTranscriptApi")
@patch("app.services.youtube.yt_dlp.YoutubeDL")
def test_e5_backward_compatibility(mock_ydl_class, mock_ytt_class, client):
    """レスポンスJSONに既存5フィールドが含まれ、型が正しい"""
    _make_ytdlp_mock(mock_ydl_class, YTDLP_INFO)
    _make_transcript_mock(mock_ytt_class)

    resp = client.post(ENDPOINT, json={"url": VALID_URL})
    data = resp.json()

    # 既存5フィールドの存在と型
    assert isinstance(data["success"], bool)
    assert isinstance(data["message"], str)
    assert isinstance(data["title"], str)
    assert isinstance(data["channel_name"], str)
    assert isinstance(data["transcript"], str)


# --- E-6: status フィールド ---

@patch("app.services.youtube.YouTubeTranscriptApi")
@patch("app.services.youtube.yt_dlp.YoutubeDL")
def test_e6_status_field(mock_ydl_class, mock_ytt_class, client):
    """成功時 status='ok'、失敗時 status='error'"""
    from youtube_transcript_api import NoTranscriptFound

    # 成功ケース
    _make_ytdlp_mock(mock_ydl_class, YTDLP_INFO)
    _make_transcript_mock(mock_ytt_class)
    resp_ok = client.post(ENDPOINT, json={"url": VALID_URL})
    assert resp_ok.json()["status"] == "ok"

    # 失敗ケース
    mock_ytt = mock_ytt_class.return_value
    mock_ytt.fetch.side_effect = NoTranscriptFound("dQw4w9WgXcQ", ["ja", "en"], {})
    resp_err = client.post(ENDPOINT, json={"url": VALID_URL})
    assert resp_err.json()["status"] == "error"


# --- E-7: transcript_language, is_generated がレスポンスに含まれる ---

@patch("app.services.youtube.YouTubeTranscriptApi")
@patch("app.services.youtube.yt_dlp.YoutubeDL")
def test_e7_transcript_metadata_in_response(mock_ydl_class, mock_ytt_class, client):
    """成功時に transcript_language と is_generated が設定されている"""
    _make_ytdlp_mock(mock_ydl_class, YTDLP_INFO)
    _make_transcript_mock(mock_ytt_class, language_code="en", is_generated=True)

    resp = client.post(ENDPOINT, json={"url": VALID_URL})
    data = resp.json()

    assert data["transcript_language"] == "en"
    assert data["is_generated"] is True
