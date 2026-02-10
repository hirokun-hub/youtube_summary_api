"""テストケース S-1〜S-6: SummaryResponse モデルの検証"""

from app.models.schemas import SummaryResponse


# S-1: 全フィールドが定義されていること
def test_s1_all_fields_defined():
    """SummaryResponse に既存5フィールド + 新規16フィールドが存在する"""
    model_fields = set(SummaryResponse.model_fields.keys())
    computed_fields = set(SummaryResponse.model_computed_fields.keys())
    all_fields = model_fields | computed_fields

    # 既存5フィールド
    assert "success" in all_fields
    assert "message" in all_fields
    assert "title" in all_fields
    assert "channel_name" in all_fields
    assert "transcript" in all_fields

    # 新規フィールド
    assert "status" in all_fields
    assert "error_code" in all_fields
    assert "upload_date" in all_fields
    assert "duration" in all_fields
    assert "duration_string" in all_fields
    assert "view_count" in all_fields
    assert "like_count" in all_fields
    assert "thumbnail_url" in all_fields
    assert "description" in all_fields
    assert "tags" in all_fields
    assert "categories" in all_fields
    assert "channel_id" in all_fields
    assert "channel_follower_count" in all_fields
    assert "webpage_url" in all_fields
    assert "transcript_language" in all_fields
    assert "is_generated" in all_fields

    # 合計 21 フィールド
    assert len(all_fields) == 21


# S-2: 成功レスポンスの生成
def test_s2_success_response():
    """全フィールドに値を入れてインスタンス化できる"""
    resp = SummaryResponse(
        success=True,
        message="Successfully retrieved data.",
        error_code=None,
        title="テスト動画",
        channel_name="テストチャンネル",
        channel_id="UCxxxx",
        channel_follower_count=1250000,
        upload_date="20260208",
        duration=360,
        duration_string="6:00",
        view_count=54000,
        like_count=1200,
        thumbnail_url="https://i.ytimg.com/vi/xxx/maxresdefault.jpg",
        description="概要欄テキスト",
        tags=["Python", "Tutorial"],
        categories=["Education"],
        webpage_url="https://www.youtube.com/watch?v=xxx",
        transcript="[00:00:00] こんにちは",
        transcript_language="ja",
        is_generated=True,
    )
    assert resp.success is True
    assert resp.title == "テスト動画"
    assert resp.duration == 360
    assert resp.tags == ["Python", "Tutorial"]


# S-3: 失敗レスポンスの生成（メタデータあり）
def test_s3_failure_with_metadata():
    """transcript=null でもインスタンス化できる"""
    resp = SummaryResponse(
        success=False,
        message="この動画には利用可能な文字起こしがありませんでした。",
        error_code="TRANSCRIPT_NOT_FOUND",
        title="テスト動画",
        channel_name="テストチャンネル",
        channel_id="UCxxxx",
        channel_follower_count=1250000,
        upload_date="20260208",
        duration=360,
        duration_string="6:00",
        view_count=54000,
        like_count=1200,
        thumbnail_url="https://i.ytimg.com/vi/xxx/maxresdefault.jpg",
        description="概要欄テキスト",
        tags=["Python"],
        categories=["Education"],
        webpage_url="https://www.youtube.com/watch?v=xxx",
        transcript=None,
        transcript_language=None,
        is_generated=None,
    )
    assert resp.success is False
    assert resp.transcript is None
    assert resp.title == "テスト動画"


# S-4: 失敗レスポンスの生成（メタデータなし）
def test_s4_failure_no_metadata():
    """全フィールド null でもインスタンス化できる"""
    resp = SummaryResponse(
        success=False,
        message="YouTubeから情報を取得できませんでした。",
        error_code="VIDEO_NOT_FOUND",
    )
    assert resp.success is False
    assert resp.title is None
    assert resp.channel_name is None
    assert resp.transcript is None
    assert resp.upload_date is None
    assert resp.duration is None
    assert resp.tags is None


# S-5: status フィールドの値
def test_s5_status_field():
    """success=True のとき status='ok'、success=False のとき status='error'"""
    ok_resp = SummaryResponse(success=True, message="ok")
    assert ok_resp.status == "ok"

    err_resp = SummaryResponse(success=False, message="error")
    assert err_resp.status == "error"


# S-6: 後方互換性
def test_s6_backward_compatibility():
    """既存5フィールドの型が変更されていない"""
    fields = SummaryResponse.model_fields

    # success: bool
    assert fields["success"].annotation is bool

    # message: str
    assert fields["message"].annotation is str

    # title: str | None
    assert fields["title"].default is None

    # channel_name: str | None
    assert fields["channel_name"].default is None

    # transcript: str | None
    assert fields["transcript"].default is None
