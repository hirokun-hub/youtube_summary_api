import os

os.environ["API_KEY"] = "test-api-key"

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from main import app
from app.core.security import verify_api_key


# --- TestClient fixtures ---

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


# --- yt-dlp テスト用固定データ ---

@pytest.fixture
def ytdlp_success_info():
    """yt-dlp extract_info の成功レスポンス"""
    return {
        "title": "テスト動画タイトル",
        "channel": "テストチャンネル",
        "channel_id": "UCxxxxxxxxxxxxxxxxxxxx",
        "channel_follower_count": 1250000,
        "upload_date": "20260208",
        "duration": 360,
        "duration_string": "6:00",
        "view_count": 54000,
        "like_count": 1200,
        "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg",
        "description": "これはテスト動画の概要欄です。",
        "tags": ["Python", "Tutorial"],
        "categories": ["Education"],
        "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    }


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
