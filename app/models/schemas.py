# app/models/schemas.py

"""
このモジュールは、APIで使用されるデータ構造（スキーマ）をPydanticモデルとして定義します。
リクエストとレスポンスの型ヒントやバリデーションに使用されます。
"""

from typing import Optional

from pydantic import BaseModel, HttpUrl, Field, computed_field

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
    # 既存フィールド（変更なし）
    success: bool = Field(..., description="処理が成功したかどうか")
    message: str = Field(..., description="処理結果のメッセージ")
    title: Optional[str] = Field(None, description="動画のタイトル")
    channel_name: Optional[str] = Field(None, description="チャンネル名")
    transcript: Optional[str] = Field(None, description="取得した文字起こし全文")

    # 新規フィールド（iPhoneショートカット対応）
    error_code: Optional[str] = Field(None, description="プログラムで判別可能なエラー種別")

    # 新規フィールド（安定性 高）
    upload_date: Optional[str] = Field(None, description="投稿日（YYYYMMDD形式）")
    duration: Optional[int] = Field(None, description="動画の長さ（秒）")
    duration_string: Optional[str] = Field(None, description="動画の長さ（'6:00'形式）")
    view_count: Optional[int] = Field(None, description="再生回数")
    thumbnail_url: Optional[str] = Field(None, description="サムネイルURL")
    description: Optional[str] = Field(None, description="概要欄テキスト")
    tags: Optional[list] = Field(None, description="タグ一覧")
    categories: Optional[list] = Field(None, description="カテゴリ一覧")
    channel_id: Optional[str] = Field(None, description="チャンネルID")
    webpage_url: Optional[str] = Field(None, description="正規化された動画URL")
    transcript_language: Optional[str] = Field(None, description="取得できた字幕の言語コード")
    is_generated: Optional[bool] = Field(None, description="自動生成字幕かどうか")

    # 新規フィールド（安定性 中）
    like_count: Optional[int] = Field(None, description="高評価数")
    channel_follower_count: Optional[int] = Field(None, description="チャンネル登録者数")

    @computed_field
    @property
    def status(self) -> str:
        """success の値から自動導出。iPhoneの言語設定に依存しない文字列での成功/失敗判定用。"""
        return "ok" if self.success else "error"

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "success": True,
                    "status": "ok",
                    "message": "Successfully retrieved data.",
                    "error_code": None,
                    "title": "テスト動画タイトル",
                    "channel_name": "テストチャンネル",
                    "channel_id": "UCxxxx",
                    "channel_follower_count": 1250000,
                    "upload_date": "20260208",
                    "duration": 360,
                    "duration_string": "6:00",
                    "view_count": 54000,
                    "like_count": 1200,
                    "thumbnail_url": "https://i.ytimg.com/vi/xxx/maxresdefault.jpg",
                    "description": "概要欄テキスト",
                    "tags": ["Python", "Tutorial"],
                    "categories": ["Education"],
                    "webpage_url": "https://www.youtube.com/watch?v=xxx",
                    "transcript": "[00:00:00] こんにちは...",
                    "transcript_language": "ja",
                    "is_generated": True,
                }
            ]
        }
    }
