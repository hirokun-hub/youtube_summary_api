# app/models/schemas.py

"""
このモジュールは、APIで使用されるデータ構造（スキーマ）をPydanticモデルとして定義します。
リクエストとレスポンスの型ヒントやバリデーションに使用されます。
"""

from pydantic import BaseModel, HttpUrl

# --- リクエストモデル ---

class VideoRequest(BaseModel):
    """
    APIへのリクエストとして受け取るデータ構造を定義します。
    """
    # HttpUrl型を使うことで、URLが正しい形式か自動でバリデーションされる
    url: HttpUrl

    # Pydanticモデルの設定
    class Config:
        # ドキュメント用にモデルの例を定義
        json_schema_extra = {
            "example": {
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
            }
        }

# --- レスポンスモデル ---

class VideoResponse(BaseModel):
    """
    APIからのレスポンスとして返すデータ構造を定義します。
    """
    title: str
    channel_name: str
    video_url: str
    upload_date: str
    view_count: int
    # like_countとsubscriber_countは安定して取得できないため、オプショナル(None許容)とする
    like_count: int | None
    subscriber_count: int | None
    transcript: str

    # Pydanticモデルの設定
    class Config:
        # ドキュメント用にモデルの例を定義
        json_schema_extra = {
            "example": {
                "title": "Rick Astley - Never Gonna Give You Up (Official Music Video)",
                "channel_name": "Rick Astley",
                "video_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "upload_date": "N/A",
                "view_count": 0,
                "like_count": None,
                "subscriber_count": None,
                "transcript": "[00:00] We're no strangers to love\n[00:04] You know the rules and so do I..."
            }
        }
