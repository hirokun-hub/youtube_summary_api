"""テストケース SR-1〜SR-7: /search 関連 Pydantic モデルの検証

設計参照: .kiro/specs/search-endpoint/design.md §3.4 / §9.2
タスク参照: .kiro/specs/search-endpoint/tasks.md Phase 1 - 2.1
"""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.models.schemas import (
    Quota,
    SearchRequest,
    SearchResponse,
    SearchResult,
    SummaryResponse,
)

# JST タイムゾーン定数（テストヘルパ用）
_JST = timezone(timedelta(hours=9))


def _make_quota(consumed: int = 408, last_call_cost: int = 102) -> Quota:
    """テスト用 Quota インスタンス生成ヘルパ。

    reset_at_utc は UTC aware、reset_at_jst は +09:00 aware で生成する
    （FR-3 のレスポンス例の表記を再現するため）。
    """
    return Quota(
        consumed_units_today=consumed,
        daily_limit=10_000,
        last_call_cost=last_call_cost,
        reset_at_utc=datetime(2026, 4, 26, 7, 0, 0, tzinfo=timezone.utc),
        reset_at_jst=datetime(2026, 4, 26, 16, 0, 0, tzinfo=_JST),
        reset_in_seconds=32_400,
    )


def _make_search_result(**overrides) -> SearchResult:
    """テスト用 SearchResult インスタンス生成ヘルパ（必須項目を全て埋める）。"""
    base: dict = {
        "video_id": "dQw4w9WgXcQ",
        "title": "テスト動画",
        "channel_name": "テストチャンネル",
        "channel_id": "UCxxxx",
        "upload_date": "2026-04-20",
        "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg",
        "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "description": "概要欄",
        "tags": ["AI"],
        "category": "News & Politics",
        "duration": 720,
        "duration_string": "12:00",
        "has_caption": True,
        "definition": "hd",
        "view_count": 120_000,
        "like_count": 8_400,
        "like_view_ratio": 0.07,
        "comment_count": 350,
        "comment_view_ratio": 0.0029,
        "channel_follower_count": 1_520_000,
        "channel_video_count": 842,
        "channel_total_view_count": 480_000_000,
        "channel_created_at": "2014-08-10",
        "channel_avg_views": 570_000,
    }
    base.update(overrides)
    return SearchResult(**base)


# --- SR-1: SearchRequest の q 必須・任意フィールド・列挙・ISO 8601 検証 ---

def test_sr1_search_request_q_required():
    """q 未指定で ValidationError"""
    with pytest.raises(ValidationError):
        SearchRequest()


def test_sr1_search_request_q_only():
    """q のみ指定でインスタンス化できる（他フィールドは任意）"""
    req = SearchRequest(q="ホリエモン")
    assert req.q == "ホリエモン"
    assert req.order is None
    assert req.published_after is None
    assert req.published_before is None
    assert req.video_duration is None
    assert req.region_code is None
    assert req.relevance_language is None
    assert req.channel_id is None


def test_sr1_search_request_order_enum_invalid():
    """order が列挙外で ValidationError"""
    with pytest.raises(ValidationError):
        SearchRequest(q="test", order="foo")


@pytest.mark.parametrize("order", ["relevance", "date", "rating", "viewCount", "title"])
def test_sr1_search_request_order_enum_valid(order):
    """order の列挙値はすべて受け入れられる"""
    req = SearchRequest(q="test", order=order)
    assert req.order == order


def test_sr1_search_request_published_after_iso8601():
    """published_after が ISO 8601 文字列を datetime に変換"""
    req = SearchRequest(q="test", published_after="2026-01-01T00:00:00Z")
    assert isinstance(req.published_after, datetime)
    assert req.published_after.year == 2026


def test_sr1_search_request_published_before_iso8601_invalid():
    """published_before が ISO 8601 不正で ValidationError"""
    with pytest.raises(ValidationError):
        SearchRequest(q="test", published_before="invalid-date")


def test_sr1_search_request_q_empty_string_invalid():
    """q が空文字列 "" で ValidationError"""
    with pytest.raises(ValidationError):
        SearchRequest(q="")


def test_sr1_search_request_q_whitespace_only_invalid():
    """q が空白のみ "   " で ValidationError（クォータ浪費の予防）"""
    with pytest.raises(ValidationError):
        SearchRequest(q="   ")


def test_sr1_search_request_q_strips_whitespace():
    """q の前後空白は除去される（"  hello  " → "hello"）"""
    req = SearchRequest(q="  hello  ")
    assert req.q == "hello"


# --- SR-1 追加: published_after / published_before は timezone-aware 必須 ---

def test_sr1_published_after_naive_rejected():
    """published_after が naive ISO 8601 ('2026-01-01T00:00:00') で ValidationError"""
    with pytest.raises(ValidationError):
        SearchRequest(q="test", published_after="2026-01-01T00:00:00")


def test_sr1_published_before_naive_rejected():
    """published_before が naive ISO 8601 で ValidationError"""
    with pytest.raises(ValidationError):
        SearchRequest(q="test", published_before="2026-04-25T23:59:59")


def test_sr1_published_after_date_only_rejected():
    """日付のみ ('2026-01-01') は naive 扱いで ValidationError"""
    with pytest.raises(ValidationError):
        SearchRequest(q="test", published_after="2026-01-01")


@pytest.mark.parametrize("value", [
    "2026-01-01T00:00:00Z",
    "2026-01-01T00:00:00+00:00",
    "2026-01-01T09:00:00+09:00",
    "2026-04-25T23:59:59-08:00",
])
def test_sr1_published_after_aware_accepted(value):
    """Z / +00:00 / +09:00 / -08:00 などの aware ISO 8601 は受け入れられる"""
    req = SearchRequest(q="test", published_after=value)
    assert req.published_after is not None
    assert req.published_after.tzinfo is not None
    assert req.published_after.utcoffset() is not None


def test_sr1_published_normalizes_to_utc_iso8601():
    """サービス層へ渡す前提として、aware datetime は astimezone(UTC).isoformat() で
    一意な RFC 3339 UTC 文字列に正規化できる（後続 service 層の契約）。"""
    req = SearchRequest(q="test", published_after="2026-01-01T09:00:00+09:00")
    assert req.published_after is not None
    utc_dt = req.published_after.astimezone(timezone.utc)
    rfc3339 = utc_dt.isoformat().replace("+00:00", "Z")
    # JST 09:00 == UTC 00:00
    assert rfc3339 == "2026-01-01T00:00:00Z"


# --- SR-2: Quota の全 7 フィールド + 派生値 ---

def test_sr2_quota_seven_fields():
    """Quota は 7 フィールド（6 素フィールド + 1 computed_field）を持つ"""
    model_fields = set(Quota.model_fields.keys())
    computed_fields = set(Quota.model_computed_fields.keys())
    all_fields = model_fields | computed_fields
    assert "consumed_units_today" in all_fields
    assert "daily_limit" in all_fields
    assert "last_call_cost" in all_fields
    assert "reset_at_utc" in all_fields
    assert "reset_at_jst" in all_fields
    assert "reset_in_seconds" in all_fields
    assert "remaining_units_estimate" in all_fields
    assert len(all_fields) == 7


def test_sr2_quota_remaining_units_computed():
    """remaining_units_estimate は daily_limit - consumed_units_today の @computed_field"""
    q = _make_quota(consumed=408)
    assert q.remaining_units_estimate == 10_000 - 408
    # daily_limit を変えても computed_field が追従する
    q2 = Quota(
        consumed_units_today=200,
        daily_limit=5_000,
        last_call_cost=100,
        reset_at_utc=datetime(2026, 4, 26, 7, 0, 0, tzinfo=timezone.utc),
        reset_at_jst=datetime(2026, 4, 26, 16, 0, 0, tzinfo=_JST),
        reset_in_seconds=10,
    )
    assert q2.remaining_units_estimate == 4_800


def test_sr2_quota_reset_in_seconds_is_plain_field():
    """reset_in_seconds は素フィールドであり、@computed_field ではない"""
    # コンストラクタに渡した値がそのまま保持される（再評価されない）
    q = _make_quota()
    assert q.reset_in_seconds == 32_400
    # computed_fields には含まれない
    assert "reset_in_seconds" not in Quota.model_computed_fields
    assert "reset_in_seconds" in Quota.model_fields


def test_sr2_quota_remaining_clamped_to_zero():
    """consumed が daily_limit を超えても remaining_units_estimate は 0 でクランプされる"""
    q = Quota(
        consumed_units_today=12_000,
        daily_limit=10_000,
        last_call_cost=0,
        reset_at_utc=datetime(2026, 4, 26, 7, 0, 0, tzinfo=timezone.utc),
        reset_at_jst=datetime(2026, 4, 26, 16, 0, 0, tzinfo=_JST),
        reset_in_seconds=0,
    )
    assert q.remaining_units_estimate == 0


# --- SR-2 追加: タイムゾーン aware を強制（FR-3 レスポンス例の表記保証） ---

def test_sr2_quota_rejects_naive_reset_at_utc():
    """reset_at_utc が naive datetime なら ValidationError"""
    with pytest.raises(ValidationError):
        Quota(
            consumed_units_today=0,
            daily_limit=10_000,
            last_call_cost=0,
            reset_at_utc=datetime(2026, 4, 26, 7, 0, 0),  # naive
            reset_at_jst=datetime(2026, 4, 26, 16, 0, 0, tzinfo=_JST),
            reset_in_seconds=0,
        )


def test_sr2_quota_rejects_naive_reset_at_jst():
    """reset_at_jst が naive datetime なら ValidationError"""
    with pytest.raises(ValidationError):
        Quota(
            consumed_units_today=0,
            daily_limit=10_000,
            last_call_cost=0,
            reset_at_utc=datetime(2026, 4, 26, 7, 0, 0, tzinfo=timezone.utc),
            reset_at_jst=datetime(2026, 4, 26, 16, 0, 0),  # naive
            reset_in_seconds=0,
        )


def test_sr2_quota_rejects_non_utc_reset_at_utc():
    """reset_at_utc が UTC 以外のオフセットなら ValidationError"""
    with pytest.raises(ValidationError):
        Quota(
            consumed_units_today=0,
            daily_limit=10_000,
            last_call_cost=0,
            reset_at_utc=datetime(2026, 4, 26, 7, 0, 0, tzinfo=_JST),  # +09:00 不可
            reset_at_jst=datetime(2026, 4, 26, 16, 0, 0, tzinfo=_JST),
            reset_in_seconds=0,
        )


def test_sr2_quota_rejects_non_jst_reset_at_jst():
    """reset_at_jst が +09:00 以外のオフセットなら ValidationError"""
    with pytest.raises(ValidationError):
        Quota(
            consumed_units_today=0,
            daily_limit=10_000,
            last_call_cost=0,
            reset_at_utc=datetime(2026, 4, 26, 7, 0, 0, tzinfo=timezone.utc),
            reset_at_jst=datetime(2026, 4, 26, 16, 0, 0, tzinfo=timezone.utc),  # UTC 不可
            reset_in_seconds=0,
        )


def test_sr2_quota_json_serialization_preserves_timezone():
    """model_dump(mode='json') 出力に Z および +09:00 が含まれる（FR-3 整合）"""
    q = _make_quota()
    dumped = q.model_dump(mode="json")
    # reset_at_utc は ISO 8601 で UTC 表記を保つ（"Z" または "+00:00"）
    assert dumped["reset_at_utc"].endswith("Z") or "+00:00" in dumped["reset_at_utc"]
    # reset_at_jst は +09:00 オフセットが保持される
    assert "+09:00" in dumped["reset_at_jst"]


# --- SR-3: SearchResult の必須フィールド存在と派生値の型 ---

def test_sr3_search_result_fields_present():
    """SearchResult に必須フィールドがすべて存在する"""
    fields = set(SearchResult.model_fields.keys())
    expected = {
        "video_id", "title", "channel_name", "channel_id", "upload_date",
        "thumbnail_url", "webpage_url", "description", "tags", "category",
        "duration", "duration_string", "has_caption", "definition",
        "view_count", "like_count", "like_view_ratio",
        "comment_count", "comment_view_ratio",
        "channel_follower_count", "channel_video_count",
        "channel_total_view_count", "channel_created_at", "channel_avg_views",
        # videos.list 強化シグナル（status / topicDetails / paidProductPlacementDetails）
        "made_for_kids", "contains_synthetic_media",
        "has_paid_product_placement", "licensed_content",
        "topic_categories", "region_blocked_countries",
    }
    assert expected.issubset(fields)


def test_sr3_search_result_derived_floats():
    """派生値（like_view_ratio, comment_view_ratio）は float | None"""
    result = _make_search_result(like_view_ratio=None, comment_view_ratio=None)
    assert result.like_view_ratio is None
    assert result.comment_view_ratio is None

    result_with_values = _make_search_result(
        like_view_ratio=0.07, comment_view_ratio=0.0029
    )
    assert isinstance(result_with_values.like_view_ratio, float)
    assert isinstance(result_with_values.comment_view_ratio, float)


def test_sr3_search_result_has_caption_bool():
    """has_caption は bool 型"""
    result_true = _make_search_result(has_caption=True)
    assert result_true.has_caption is True
    result_false = _make_search_result(has_caption=False)
    assert result_false.has_caption is False


# --- SR-4: SearchResponse の success/error_code 整合 + quota フィールド ---

def test_sr4_search_response_success_ok():
    """success=True, error_code=None, results=[] でインスタンス化できる"""
    resp = SearchResponse(
        success=True,
        message="Successfully retrieved 0 results.",
        error_code=None,
        query="test",
        total_results_estimate=0,
        returned_count=0,
        results=[],
        quota=_make_quota(),
    )
    assert resp.success is True
    assert resp.status == "ok"
    assert resp.error_code is None
    assert resp.quota is not None


def test_sr4_search_response_error_status():
    """success=False の時 status='error'"""
    resp = SearchResponse(
        success=False,
        message="検索レート制限",
        error_code="CLIENT_RATE_LIMITED",
        query="test",
        retry_after=12,
        quota=_make_quota(last_call_cost=0),
    )
    assert resp.success is False
    assert resp.status == "error"


def test_sr4_search_response_success_with_error_code_invalid():
    """success=True かつ error_code が None でない場合 ValidationError"""
    with pytest.raises(ValidationError):
        SearchResponse(
            success=True,
            message="...",
            error_code="INTERNAL_ERROR",
            query="test",
        )


def test_sr4_search_response_failure_without_error_code_invalid():
    """success=False かつ error_code が None の場合 ValidationError"""
    with pytest.raises(ValidationError):
        SearchResponse(
            success=False,
            message="...",
            error_code=None,
            query="test",
        )


def test_sr4_search_response_401_excludes_quota_key_in_dump():
    """401 (UNAUTHORIZED) レスポンスは exclude_none=True で quota キーが完全に欠落する。

    要件 FR-4/FR-5 では「401 には quota フィールドなし」（None ではなくキー自体不在）。
    後続 router は exclude_none=True で出力する契約をここで固定する。
    """
    resp = SearchResponse(
        success=False,
        message="X-API-KEY ヘッダが不正または未設定です。",
        error_code="UNAUTHORIZED",
        query=None,
        quota=None,
    )
    # exclude_none=True で 401 レスポンスを出力すると quota キーは含まれない
    dumped = resp.model_dump(exclude_none=True)
    assert "quota" not in dumped
    # 同時に query / results / retry_after も None なので出力されない
    assert "query" not in dumped
    assert "results" not in dumped
    assert "retry_after" not in dumped
    # 必須情報は含まれる
    assert dumped["error_code"] == "UNAUTHORIZED"
    assert dumped["success"] is False


# --- SR-5: 新規レスポンスモデルが frozen=True, extra="forbid" ---

def test_sr5_quota_frozen():
    """Quota は frozen=True であり、属性代入で ValidationError"""
    q = _make_quota()
    with pytest.raises(ValidationError):
        q.consumed_units_today = 999  # type: ignore[misc]


def test_sr5_quota_extra_forbid():
    """Quota は extra='forbid'。未知フィールドで ValidationError"""
    with pytest.raises(ValidationError):
        Quota(
            consumed_units_today=0,
            daily_limit=10_000,
            last_call_cost=0,
            reset_at_utc=datetime(2026, 4, 26, 7, 0, 0, tzinfo=timezone.utc),
            reset_at_jst=datetime(2026, 4, 26, 16, 0, 0),
            reset_in_seconds=0,
            unknown_field="x",
        )


def test_sr5_search_result_frozen():
    """SearchResult は frozen=True"""
    result = _make_search_result()
    with pytest.raises(ValidationError):
        result.title = "new"  # type: ignore[misc]


def test_sr5_search_result_extra_forbid():
    """SearchResult は extra='forbid'"""
    with pytest.raises(ValidationError):
        _make_search_result(unknown_field="x")


def test_sr5_search_response_frozen():
    """SearchResponse は frozen=True"""
    resp = SearchResponse(
        success=False,
        message="...",
        error_code="UNAUTHORIZED",
        query=None,
    )
    with pytest.raises(ValidationError):
        resp.message = "changed"  # type: ignore[misc]


def test_sr5_search_response_extra_forbid():
    """SearchResponse は extra='forbid'"""
    with pytest.raises(ValidationError):
        SearchResponse(
            success=True,
            message="ok",
            error_code=None,
            query="test",
            unknown_field="x",
        )


def test_sr5_search_request_extra_forbid():
    """SearchRequest は extra='forbid'（frozen は不要）"""
    with pytest.raises(ValidationError):
        SearchRequest(q="test", unknown_field="x")


# --- SR-6: SearchResult に transcript 系フィールドが存在しない ---

def test_sr6_no_transcript_fields_in_search_result():
    """SearchResult に transcript / transcript_language / is_generated が存在しない"""
    fields = set(SearchResult.model_fields.keys())
    assert "transcript" not in fields
    assert "transcript_language" not in fields
    assert "is_generated" not in fields


# --- SR-7: SummaryResponse.quota が Optional で追加され、既存フィールド不変 ---

def test_sr7_summary_response_has_quota_field():
    """SummaryResponse に quota: Quota | None フィールドが追加されている"""
    fields = SummaryResponse.model_fields
    assert "quota" in fields
    # デフォルト値は None
    assert fields["quota"].default is None


def test_sr7_summary_response_quota_optional_omittable():
    """quota を省略しても valid（既存呼び出しの後方互換）"""
    resp = SummaryResponse(success=True, message="ok")
    assert resp.quota is None


def test_sr7_summary_response_quota_accepts_quota_instance():
    """quota に Quota インスタンスを渡せる"""
    quota = _make_quota(last_call_cost=2)
    resp = SummaryResponse(success=True, message="ok", quota=quota)
    assert resp.quota is not None
    assert resp.quota.last_call_cost == 2


def test_sr7_summary_response_existing_fields_unchanged():
    """既存 22 フィールド（21 素 + 1 computed status）の名前と型が完全に不変"""
    fields = SummaryResponse.model_fields
    # 既存フィールドが消えていない
    expected_existing = {
        "success", "message", "title", "channel_name", "transcript",
        "error_code", "upload_date", "duration", "duration_string",
        "view_count", "thumbnail_url", "description", "tags", "categories",
        "channel_id", "webpage_url", "transcript_language", "is_generated",
        "like_count", "channel_follower_count", "retry_after",
    }
    assert expected_existing.issubset(set(fields.keys()))
    # 既存型が変わっていない
    assert fields["success"].annotation is bool
    assert fields["message"].annotation is str
    # status は computed_field
    assert "status" in SummaryResponse.model_computed_fields


# --- SR-8: videos.list 強化シグナルの 6 フィールドが Optional default None ---

def test_sr8_search_result_new_signal_fields_optional_default_none():
    """status / topicDetails / paidProductPlacementDetails 由来の 6 フィールドは
    すべて `is_required() == False`（Optional default None）であること。

    既存 SearchResult に対する後方互換（古いクライアントが新フィールドを送らなくても valid）
    を保証する。
    """
    fields = SearchResult.model_fields
    new_fields = {
        "made_for_kids",
        "contains_synthetic_media",
        "has_paid_product_placement",
        "licensed_content",
        "topic_categories",
        "region_blocked_countries",
    }
    for name in new_fields:
        assert name in fields, f"{name} が SearchResult.model_fields に存在しない"
        assert fields[name].is_required() is False, (
            f"{name} は Optional default None であるべき (is_required() == False)"
        )
        assert fields[name].default is None, (
            f"{name} のデフォルト値は None であるべき"
        )

    # 実際にこれらを省略してもインスタンス化できる（既存ヘルパで生成される _make_search_result が成立済み）
    result = _make_search_result()
    for name in new_fields:
        assert getattr(result, name) is None
