# app/models/schemas.py

"""
このモジュールは、APIで使用されるデータ構造（スキーマ）をPydanticモデルとして定義します。
リクエストとレスポンスの型ヒントやバリデーションに使用されます。
"""

from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    computed_field,
    field_validator,
    model_validator,
)

# JST タイムゾーン定数（reset_at_jst のオフセット検証用）
_JST = timezone(timedelta(hours=9))

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


class SearchRequest(BaseModel):
    """POST /api/v1/search リクエストボディ。"""
    model_config = ConfigDict(extra="forbid")

    # strip_whitespace=True で空白のみ ("   ") を弾く（無意味な検索による YouTube クォータ浪費の予防）
    q: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] = Field(
        ..., description="検索クエリ（必須・空白のみは不可）"
    )
    order: Optional[str] = Field(
        None,
        pattern="^(relevance|date|rating|viewCount|title)$",
        description="並び順",
    )
    published_after: Optional[datetime] = Field(
        None,
        description="この日時以降に投稿された動画のみ（RFC 3339 / timezone-aware 必須）",
    )
    published_before: Optional[datetime] = Field(
        None,
        description="この日時以前に投稿された動画のみ（RFC 3339 / timezone-aware 必須）",
    )
    video_duration: Optional[str] = Field(
        None,
        pattern="^(any|short|medium|long)$",
        description="動画の長さフィルタ",
    )
    region_code: Optional[str] = Field(
        None,
        pattern="^[A-Z]{2}$",
        description="地域コード（ISO 3166-1 alpha-2）",
    )
    relevance_language: Optional[str] = Field(
        None,
        pattern="^[a-z]{2}$",
        description="関連言語コード（ISO 639-1）",
    )
    channel_id: Optional[str] = Field(None, description="特定チャンネル内検索")

    @field_validator("published_after", "published_before")
    @classmethod
    def _ensure_published_aware(cls, v: Optional[datetime]) -> Optional[datetime]:
        """published_after / published_before は timezone-aware datetime のみ許可する。

        理由: YouTube Data API v3 の publishedAfter/Before パラメタは RFC 3339
        （タイムゾーン必須）。naive を受けると UTC か JST かの解釈が曖昧になり、
        AI クライアントの入力ミスでクォータを浪費する原因となる。
        サービス層では `astimezone(timezone.utc)` で UTC RFC3339 文字列に正規化する。
        """
        if v is None:
            return v
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError(
                "published_after / published_before は timezone-aware (例: 'Z' または "
                "'+09:00' 付き ISO 8601 / RFC 3339) で指定してください"
            )
        return v


# --- レスポンスモデル ---

class Quota(BaseModel):
    """API クォータ状態（レスポンス同梱用）。

    `reset_in_seconds` は応答時刻で確定した値を quota_tracker.get_snapshot から
    受け取る素フィールド。@computed_field にしないのは、シリアライズ時刻ごとに
    datetime.now() が再評価されると reset_at_utc との整合が取れなくなるため。
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    consumed_units_today: int = Field(..., description="本日消費した units 累計（推定）")
    daily_limit: int = Field(10_000, description="日次クォータ上限")
    last_call_cost: int = Field(..., description="本リクエストで消費した units")
    reset_at_utc: datetime = Field(..., description="次のリセット時刻（UTC）")
    reset_at_jst: datetime = Field(..., description="次のリセット時刻（JST）")
    reset_in_seconds: int = Field(..., description="次のリセットまでの残り秒数（応答時点で確定）")

    @computed_field
    @property
    def remaining_units_estimate(self) -> int:
        """daily_limit - consumed_units_today（負値はゼロにクランプ）"""
        return max(0, self.daily_limit - self.consumed_units_today)

    @field_validator("reset_at_utc")
    @classmethod
    def _ensure_utc_aware(cls, v: datetime) -> datetime:
        """reset_at_utc は UTC オフセットの aware datetime のみ受け入れる。

        AI クライアントが「Z 表記の絶対時刻」として安全に解釈できるよう、
        naive や非 UTC タイムゾーンは拒否する。
        """
        if v.tzinfo is None:
            raise ValueError("reset_at_utc は timezone-aware である必要があります")
        if v.utcoffset() != timedelta(0):
            raise ValueError("reset_at_utc は UTC (+00:00) である必要があります")
        return v

    @field_validator("reset_at_jst")
    @classmethod
    def _ensure_jst_aware(cls, v: datetime) -> datetime:
        """reset_at_jst は +09:00 オフセットの aware datetime のみ受け入れる。

        FR-3 のレスポンス例 "2026-04-26T16:00:00+09:00" を保証するため、
        naive や他オフセットは拒否する。
        """
        if v.tzinfo is None:
            raise ValueError("reset_at_jst は timezone-aware である必要があります")
        if v.utcoffset() != timedelta(hours=9):
            raise ValueError("reset_at_jst は +09:00 オフセットである必要があります")
        return v


class SearchResult(BaseModel):
    """検索結果 1 件分の動画情報。"""
    model_config = ConfigDict(frozen=True, extra="forbid")

    video_id: str = Field(..., description="YouTube 動画 ID")
    title: str = Field(..., description="動画タイトル")
    channel_name: str = Field(..., description="チャンネル名")
    channel_id: str = Field(..., description="チャンネル ID")
    upload_date: Optional[str] = Field(None, description="投稿日（YYYY-MM-DD）")
    thumbnail_url: Optional[str] = Field(None, description="サムネイル URL（最高優先度を選択）")
    webpage_url: str = Field(..., description="動画 URL")
    description: str = Field(..., description="概要欄テキスト")
    tags: Optional[list[str]] = Field(None, description="タグ一覧")
    category: Optional[str] = Field(None, description="カテゴリ名")
    duration: Optional[int] = Field(None, description="動画の長さ（秒）")
    duration_string: Optional[str] = Field(None, description="動画の長さ（'mm:ss'形式）")
    has_caption: bool = Field(..., description="字幕の有無（contentDetails.caption 由来）")
    definition: Optional[str] = Field(None, description="動画品質（'hd' / 'sd'）")

    view_count: Optional[int] = Field(None, description="再生回数")
    like_count: Optional[int] = Field(None, description="高評価数")
    like_view_ratio: Optional[float] = Field(None, description="like_count / view_count")
    comment_count: Optional[int] = Field(None, description="コメント数")
    comment_view_ratio: Optional[float] = Field(None, description="comment_count / view_count")

    channel_follower_count: Optional[int] = Field(None, description="チャンネル登録者数")
    channel_video_count: Optional[int] = Field(None, description="チャンネル動画総数")
    channel_total_view_count: Optional[int] = Field(None, description="チャンネル累計再生数")
    channel_created_at: Optional[str] = Field(None, description="チャンネル作成日（YYYY-MM-DD）")
    channel_avg_views: Optional[int] = Field(None, description="チャンネル動画あたり平均再生数")


class SearchResponse(BaseModel):
    """POST /api/v1/search レスポンス。"""
    model_config = ConfigDict(frozen=True, extra="forbid")

    success: bool = Field(..., description="処理が成功したかどうか")
    message: str = Field(..., description="処理結果のメッセージ")
    error_code: Optional[str] = Field(None, description="プログラムで判別可能なエラー種別")
    query: Optional[str] = Field(None, description="検索クエリ（リクエストの q）")
    total_results_estimate: Optional[int] = Field(None, description="YouTube が返した推定総ヒット数")
    returned_count: Optional[int] = Field(None, description="返却した結果件数")
    results: Optional[list[SearchResult]] = Field(None, description="検索結果配列")
    retry_after: Optional[int] = Field(None, description="再試行までの待ち秒数")
    quota: Optional[Quota] = Field(None, description="API クォータ状態（401/422 では None）")

    @computed_field
    @property
    def status(self) -> str:
        """success の値から自動導出。"""
        return "ok" if self.success else "error"

    @model_validator(mode="after")
    def _check_error_correlation(self) -> "SearchResponse":
        if self.success and self.error_code is not None:
            raise ValueError("success=True なら error_code は None")
        if not self.success and self.error_code is None:
            raise ValueError("success=False なら error_code は必須")
        return self


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
    upload_date: Optional[str] = Field(None, description="投稿日（ISO 8601形式: YYYY-MM-DD）")
    duration: Optional[int] = Field(None, description="動画の長さ（秒）")
    duration_string: Optional[str] = Field(None, description="動画の長さ（'6:00'形式）")
    view_count: Optional[int] = Field(None, description="再生回数")
    thumbnail_url: Optional[str] = Field(None, description="サムネイルURL")
    description: Optional[str] = Field(None, description="概要欄テキスト")
    tags: Optional[list[str]] = Field(None, description="タグ一覧")
    categories: Optional[list[str]] = Field(None, description="カテゴリ一覧")
    channel_id: Optional[str] = Field(None, description="チャンネルID")
    webpage_url: Optional[str] = Field(None, description="正規化された動画URL")
    transcript_language: Optional[str] = Field(None, description="取得できた字幕の言語コード")
    is_generated: Optional[bool] = Field(None, description="自動生成字幕かどうか")

    # 新規フィールド（安定性 中）
    like_count: Optional[int] = Field(None, description="高評価数")
    channel_follower_count: Optional[int] = Field(None, description="チャンネル登録者数")

    # 新規フィールド（クライアント側レート制限時のみ非null）
    retry_after: Optional[int] = Field(None, description="次のリクエストまで待つべき秒数（クライアント側レート制限時のみ）")

    # 新規フィールド（クォータ状態同梱、既存挙動には影響なし）
    quota: Optional[Quota] = Field(None, description="API クォータ状態（業務処理を通った場合に付与）")

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
                    "upload_date": "2026-02-08",
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
                    "quota": {
                        "consumed_units_today": 408,
                        "daily_limit": 10000,
                        "last_call_cost": 2,
                        "reset_at_utc": "2026-04-26T07:00:00Z",
                        "reset_at_jst": "2026-04-26T16:00:00+09:00",
                        "reset_in_seconds": 32400,
                        "remaining_units_estimate": 9592,
                    },
                }
            ]
        }
    }
