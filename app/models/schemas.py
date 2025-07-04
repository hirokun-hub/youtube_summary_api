# app/models/schemas.py

"""
このモジュールは、APIで使用されるデータ構造（スキーマ）をPydanticモデルとして定義します。
リクエストとレスポンスの型ヒントやバリデーションに使用されます。
"""

from pydantic import BaseModel, HttpUrl, Field

# --- リクエストモデル ---

class VideoRequest(BaseModel):
    """
    APIへのリクエストとして受け取るデータ構造を定義します。
    """
    # HttpUrl型を使うことで、URLが正しい形式か自動でバリデーションされる
    url: HttpUrl

    # Pydantic v2では model_config を使用
    model_config = {
        "json_schema_extra": {
            "example": {
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
            }
        }
    }

# --- レスポンスモデル ---

class SummaryResponse(BaseModel):
    """APIのレスポンスとして返すYouTubeの情報"""
    success: bool = Field(..., description="処理が成功したかどうか")
    message: str = Field(..., description="処理結果のメッセージ")
    title: str | None = Field(None, description="動画のタイトル")
    channel_name: str | None = Field(None, description="チャンネル名")
    transcript: str | None = Field(None, description="取得した文字起こし全文")

    # Pydantic v2では model_config を使用
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "success": True,
                    "message": "Successfully retrieved data.",
                    "title": "Rick Astley - Never Gonna Give You Up (Official Music Video)",
                    "channel_name": "Rick Astley",
                    "transcript": "We're no strangers to love..."
                }
            ]
        }
    }
