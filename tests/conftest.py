import os

os.environ["API_KEY"] = "test-api-key"

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from main import app
from app.core.security import verify_api_key


# --- TestClient fixtures ---

@pytest.fixture(autouse=True)
def mock_youtube_api_key(monkeypatch):
    """全テストで YOUTUBE_API_KEY を設定する。"""
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-youtube-api-key")


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """各テスト前後にレートリミッタの内部状態をリセットする。

    プロセス内グローバル状態のため、テスト間の干渉を防ぐ。
    """
    from app.core import rate_limiter
    rate_limiter.reset()
    yield
    rate_limiter.reset()

@pytest.fixture
def client():
    """認証をバイパスする通常テスト用クライアント"""
    app.dependency_overrides[verify_api_key] = lambda: "test-key"
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def client_no_auth_override():
    """認証バイパスなしのクライアント（E-2テスト用）"""
    app.dependency_overrides.clear()
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def oembed_success_json():
    """oEmbed API の成功レスポンス"""
    return {
        "title": "テスト動画タイトル",
        "author_name": "テストチャンネル",
        "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
    }


@pytest.fixture
def transcript_fetched_mock():
    """youtube-transcript-api v1.2.x の FetchedTranscript モック"""
    mock = MagicMock()
    mock.language_code = "ja"
    mock.is_generated = False
    mock.to_raw_data.return_value = [
        {"text": "こんにちは", "start": 0.0, "duration": 1.5},
        {"text": "テストです", "start": 1.5, "duration": 2.0},
        {"text": "終わりです", "start": 3661.0, "duration": 1.0},
    ]
    return mock


# --- YouTube Data API v3 テスト用固定データ ---

@pytest.fixture
def youtube_api_v3_video_response():
    """YouTube Data API v3 videos.list の成功レスポンス"""
    return {
        "items": [{
            "snippet": {
                "title": "テスト動画タイトル",
                "channelTitle": "テストチャンネル",
                "channelId": "UCxxxxxxxxxxxxxxxxxxxx",
                "publishedAt": "2026-02-08T10:00:00Z",
                "description": "これはテスト動画の概要欄です。",
                "thumbnails": {
                    "default": {"url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/default.jpg"},
                    "medium": {"url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg"},
                    "high": {"url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"},
                    "standard": {"url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/sddefault.jpg"},
                    "maxres": {"url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg"},
                },
                "tags": ["Python", "Tutorial"],
                "categoryId": "27",
            },
            "contentDetails": {
                "duration": "PT6M",
            },
            "statistics": {
                "viewCount": "54000",
                "likeCount": "1200",
            },
        }],
    }


@pytest.fixture
def youtube_api_v3_channel_response():
    """YouTube Data API v3 channels.list の成功レスポンス"""
    return {
        "items": [{
            "statistics": {
                "subscriberCount": "1250000",
                "hiddenSubscriberCount": False,
            },
        }],
    }


@pytest.fixture
def youtube_api_v3_empty_response():
    """YouTube Data API v3 の空レスポンス（動画なし/非公開/削除済み）"""
    return {"items": []}


@pytest.fixture
def youtube_api_v3_quota_error():
    """YouTube Data API v3 のクォータ超過エラーレスポンス"""
    return {
        "error": {
            "code": 403,
            "message": "The request cannot be completed because you have exceeded your quota.",
            "errors": [{
                "message": "The request cannot be completed because you have exceeded your quota.",
                "domain": "youtube.quota",
                "reason": "quotaExceeded",
            }],
        },
    }
