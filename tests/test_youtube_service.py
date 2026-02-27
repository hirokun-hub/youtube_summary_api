"""テストケース Y-1〜Y-17: サービス層の単体テスト（モック使用）"""

import logging
from unittest.mock import patch, MagicMock
from unittest.mock import call

import pytest

from app.core.constants import (
    ERROR_INTERNAL,
    ERROR_INVALID_URL,
    ERROR_METADATA_FAILED,
    ERROR_RATE_LIMITED,
    ERROR_TRANSCRIPT_DISABLED,
    ERROR_TRANSCRIPT_NOT_FOUND,
    ERROR_VIDEO_NOT_FOUND,
    MSG_RATE_LIMITED,
    MSG_QUOTA_EXCEEDED,
    MSG_SUCCESS,
    TRANSCRIPT_LANGUAGES,
)
from app.services.youtube import (
    ApiCallResult,
    _build_metadata_from_youtube_api,
    _call_youtube_api_with_retry,
    _classify_api_error,
    _extract_video_id,
    _fetch_metadata_youtube_api,
    _format_duration_string,
    _parse_iso8601_duration,
    _select_best_thumbnail,
    get_summary_data,
)


VALID_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def _resp(status_code: int, payload: dict):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


# --- Y-1: 正常系 全データ取得成功 ---

@patch("app.services.youtube.requests.get")
@patch("app.services.youtube.YouTubeTranscriptApi")
def test_y1_success_all_data(mock_ytt_class, mock_requests_get,
                              youtube_api_v3_video_response, youtube_api_v3_channel_response,
                              transcript_fetched_mock):
    """v3メタデータ成功 + transcript成功 → success=True, 全フィールドに値。"""
    mock_requests_get.side_effect = [
        _resp(200, youtube_api_v3_video_response),
        _resp(200, youtube_api_v3_channel_response),
    ]

    mock_ytt = mock_ytt_class.return_value
    mock_ytt.fetch.return_value = transcript_fetched_mock

    result = get_summary_data(VALID_URL)

    assert result.success is True
    assert result.status == "ok"
    assert result.message == MSG_SUCCESS
    assert result.error_code is None
    assert result.title == "テスト動画タイトル"
    assert result.channel_name == "テストチャンネル"
    assert result.upload_date == "2026-02-08"
    assert result.duration == 360
    assert result.duration_string == "6:00"
    assert result.view_count == 54000
    assert result.like_count == 1200
    assert result.channel_id == "UCxxxxxxxxxxxxxxxxxxxx"
    assert result.channel_follower_count == 1250000
    assert result.thumbnail_url == "https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg"
    assert result.description == "これはテスト動画の概要欄です。"
    assert result.tags == ["Python", "Tutorial"]
    assert result.categories == ["Education"]
    assert result.webpage_url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert result.transcript is not None
    assert result.transcript_language == "ja"
    assert result.is_generated is False


# --- Y-2: 正常系 v3失敗→oEmbedフォールバック + transcript成功 ---

@patch("app.services.youtube.time.sleep")
@patch("app.services.youtube.requests.get")
@patch("app.services.youtube.YouTubeTranscriptApi")
def test_y2_ytdlp_fallback_oembed(mock_ytt_class, mock_requests_get, mock_sleep,
                                  oembed_success_json, transcript_fetched_mock):
    """v3がリトライ枯渇してoEmbed成功 + transcript成功 → success=True。"""
    retry_resp = _resp(503, {})
    oembed_resp = _resp(200, oembed_success_json)
    mock_requests_get.side_effect = [retry_resp, retry_resp, retry_resp, retry_resp, oembed_resp]

    mock_ytt = mock_ytt_class.return_value
    mock_ytt.fetch.return_value = transcript_fetched_mock

    result = get_summary_data(VALID_URL)

    assert result.success is True
    assert result.error_code == ERROR_METADATA_FAILED
    assert result.title == "テスト動画タイトル"
    assert result.channel_name == "テストチャンネル"
    assert result.thumbnail_url == "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"
    assert result.upload_date is None
    assert result.duration is None
    assert result.view_count is None
    assert mock_sleep.call_args_list == [call(1), call(2), call(4)]


# --- Y-3: 異常系 字幕なし + メタデータ成功 ---

@patch("app.services.youtube.requests.get")
@patch("app.services.youtube.YouTubeTranscriptApi")
def test_y3_no_transcript(mock_ytt_class, mock_requests_get, youtube_api_v3_video_response, youtube_api_v3_channel_response):
    """v3メタデータ成功 + NoTranscriptFound → TRANSCRIPT_NOT_FOUND。"""
    from youtube_transcript_api import NoTranscriptFound

    mock_requests_get.side_effect = [
        _resp(200, youtube_api_v3_video_response),
        _resp(200, youtube_api_v3_channel_response),
    ]

    mock_ytt = mock_ytt_class.return_value
    mock_ytt.fetch.side_effect = NoTranscriptFound("dQw4w9WgXcQ", ["ja", "en"], {})

    result = get_summary_data(VALID_URL)

    assert result.success is False
    assert result.error_code == ERROR_TRANSCRIPT_NOT_FOUND
    assert result.title == "テスト動画タイトル"
    assert result.upload_date == "2026-02-08"
    assert result.transcript is None


# --- Y-4: 異常系 動画が存在しない ---

@patch("app.services.youtube.requests.get")
@patch("app.services.youtube.YouTubeTranscriptApi")
def test_y4_video_not_found(mock_ytt_class, mock_requests_get):
    """videos.list で items=[] を返すと VIDEO_NOT_FOUND で短絡終了。"""
    mock_requests_get.return_value = _resp(200, {"items": []})

    result = get_summary_data(VALID_URL)

    assert result.success is False
    assert result.error_code == ERROR_VIDEO_NOT_FOUND
    assert result.title is None
    mock_ytt_class.return_value.fetch.assert_not_called()


# --- Y-5: 異常系 無効なURL ---

def test_y5_invalid_url():
    """無効なURL → success=False, error_code=INVALID_URL"""
    result = get_summary_data("https://example.com/not-a-youtube-video")

    assert result.success is False
    assert result.error_code == ERROR_INVALID_URL
    assert result.title is None
    assert result.transcript is None


# --- Y-6: 異常系 レート制限（YouTubeRequestFailed） ---

@patch("app.services.youtube.requests.get")
@patch("app.services.youtube.YouTubeTranscriptApi")
def test_y6_rate_limited(mock_ytt_class, mock_requests_get, youtube_api_v3_video_response, youtube_api_v3_channel_response):
    """YouTubeRequestFailed → success=False, error_code=RATE_LIMITED"""
    from youtube_transcript_api import YouTubeRequestFailed

    mock_requests_get.side_effect = [
        _resp(200, youtube_api_v3_video_response),
        _resp(200, youtube_api_v3_channel_response),
    ]

    mock_ytt = mock_ytt_class.return_value
    mock_http_error = MagicMock()
    mock_ytt.fetch.side_effect = YouTubeRequestFailed("dQw4w9WgXcQ", mock_http_error)

    result = get_summary_data(VALID_URL)

    assert result.success is False
    assert result.error_code == ERROR_RATE_LIMITED
    assert result.message == MSG_RATE_LIMITED


# --- Y-7: 異常系 予期せぬエラー ---

@patch("app.services.youtube.requests.get")
@patch("app.services.youtube.YouTubeTranscriptApi")
def test_y7_internal_error(mock_ytt_class, mock_requests_get, youtube_api_v3_video_response, youtube_api_v3_channel_response):
    """任意のException → success=False, error_code=INTERNAL_ERROR"""
    mock_requests_get.side_effect = [
        _resp(200, youtube_api_v3_video_response),
        _resp(200, youtube_api_v3_channel_response),
    ]

    mock_ytt = mock_ytt_class.return_value
    mock_ytt.fetch.side_effect = RuntimeError("unexpected")

    result = get_summary_data(VALID_URL)

    assert result.success is False
    assert result.error_code == ERROR_INTERNAL


# --- Y-8: 安定性中フィールドの欠損 ---

@patch("app.services.youtube.requests.get")
@patch("app.services.youtube.YouTubeTranscriptApi")
def test_y8_missing_optional_fields(mock_ytt_class, mock_requests_get,
                                     youtube_api_v3_video_response, youtube_api_v3_channel_response,
                                     transcript_fetched_mock):
    """v3成功だが likeCount欠損 + hiddenSubscriberCount=true → 該当フィールドがnull。"""
    video_resp = {**youtube_api_v3_video_response}
    video_item = {**video_resp["items"][0]}
    video_item["statistics"] = {"viewCount": "54000"}
    video_resp["items"] = [video_item]

    channel_resp = {
        "items": [{
            "statistics": {
                "hiddenSubscriberCount": True,
            }
        }]
    }

    mock_requests_get.side_effect = [
        _resp(200, video_resp),
        _resp(200, channel_resp),
    ]

    mock_ytt = mock_ytt_class.return_value
    mock_ytt.fetch.return_value = transcript_fetched_mock

    result = get_summary_data(VALID_URL)

    assert result.success is True
    assert result.like_count is None
    assert result.channel_follower_count is None
    assert result.title == "テスト動画タイトル"


# --- Y-9: transcript_language と is_generated の取得 ---

@patch("app.services.youtube.requests.get")
@patch("app.services.youtube.YouTubeTranscriptApi")
def test_y9_transcript_metadata(mock_ytt_class, mock_requests_get,
                                 youtube_api_v3_video_response, youtube_api_v3_channel_response, transcript_fetched_mock):
    """FetchedTranscript.language_code と FetchedTranscript.is_generated が正しく設定される"""
    mock_requests_get.side_effect = [
        _resp(200, youtube_api_v3_video_response),
        _resp(200, youtube_api_v3_channel_response),
    ]

    mock_ytt = mock_ytt_class.return_value
    mock_ytt.fetch.return_value = transcript_fetched_mock

    result = get_summary_data(VALID_URL)

    assert result.transcript_language == "ja"
    assert result.is_generated is False


# --- Y-10: yt-dlp DownloadError → error_code マッピング ---

@patch("app.services.youtube.time.sleep")
@patch("app.services.youtube.requests.get")
@patch("app.services.youtube.YouTubeTranscriptApi")
def test_y10_metadata_failed(mock_ytt_class, mock_requests_get, mock_sleep,
                              oembed_success_json, transcript_fetched_mock):
    """v3失敗 + oEmbed成功 + transcript成功 → error_code=METADATA_FAILED。"""
    retry_resp = _resp(503, {})
    oembed_resp = _resp(200, oembed_success_json)
    mock_requests_get.side_effect = [retry_resp, retry_resp, retry_resp, retry_resp, oembed_resp]

    mock_ytt = mock_ytt_class.return_value
    mock_ytt.fetch.return_value = transcript_fetched_mock

    result = get_summary_data(VALID_URL)

    assert result.success is True
    assert result.error_code == ERROR_METADATA_FAILED
    assert mock_sleep.call_args_list == [call(1), call(2), call(4)]


# --- Y-11: transcript の後方互換性 ---

@patch("app.services.youtube.requests.get")
@patch("app.services.youtube.YouTubeTranscriptApi")
def test_y11_transcript_format(mock_ytt_class, mock_requests_get,
                                youtube_api_v3_video_response, youtube_api_v3_channel_response, transcript_fetched_mock):
    """transcriptフォーマットが [HH:MM:SS] テキスト のタイムスタンプ付き"""
    mock_requests_get.side_effect = [
        _resp(200, youtube_api_v3_video_response),
        _resp(200, youtube_api_v3_channel_response),
    ]

    mock_ytt = mock_ytt_class.return_value
    mock_ytt.fetch.return_value = transcript_fetched_mock

    result = get_summary_data(VALID_URL)

    lines = result.transcript.split("\n")
    assert lines[0] == "[00:00:00] こんにちは"
    assert lines[1] == "[00:00:01] テストです"
    # 3661秒 = 1時間1分1秒
    assert lines[2] == "[01:01:01] 終わりです"


# --- Y-12: yt-dlp戻り値にキーが存在しない場合 ---

@patch("app.services.youtube.requests.get")
@patch("app.services.youtube.YouTubeTranscriptApi")
def test_y12_ytdlp_missing_keys(mock_ytt_class, mock_requests_get, transcript_fetched_mock):
    """v3成功だがレスポンスキー欠損時はnullで返る。"""
    minimal_video_resp = {
        "items": [{
            "snippet": {
                "title": "最小限の動画",
                "channelTitle": "最小チャンネル",
                "channelId": "UCmin",
            },
            "contentDetails": {},
            "statistics": {},
        }]
    }
    minimal_channel_resp = {"items": [{}]}
    mock_requests_get.side_effect = [
        _resp(200, minimal_video_resp),
        _resp(200, minimal_channel_resp),
    ]

    mock_ytt = mock_ytt_class.return_value
    mock_ytt.fetch.return_value = transcript_fetched_mock

    result = get_summary_data(VALID_URL)

    assert result.success is True
    assert result.title == "最小限の動画"
    assert result.channel_name == "最小チャンネル"
    assert result.duration is None
    assert result.duration_string is None
    assert result.categories is None
    assert result.tags is None
    assert result.view_count is None


# --- Y-13: error_code 7種の全カバレッジ ---

def test_y13_all_error_codes_defined():
    """7種のエラーコードが全て定数として定義されている"""
    assert ERROR_INVALID_URL == "INVALID_URL"
    assert ERROR_VIDEO_NOT_FOUND == "VIDEO_NOT_FOUND"
    assert ERROR_TRANSCRIPT_NOT_FOUND == "TRANSCRIPT_NOT_FOUND"
    assert ERROR_TRANSCRIPT_DISABLED == "TRANSCRIPT_DISABLED"
    assert ERROR_RATE_LIMITED == "RATE_LIMITED"
    assert ERROR_METADATA_FAILED == "METADATA_FAILED"
    assert ERROR_INTERNAL == "INTERNAL_ERROR"


# --- Y-14: 異常系 字幕機能が無効化 ---

@patch("app.services.youtube.requests.get")
@patch("app.services.youtube.YouTubeTranscriptApi")
def test_y14_transcripts_disabled(mock_ytt_class, mock_requests_get, youtube_api_v3_video_response, youtube_api_v3_channel_response):
    """TranscriptsDisabled → success=False, error_code=TRANSCRIPT_DISABLED, メタデータあり"""
    from youtube_transcript_api import TranscriptsDisabled

    mock_requests_get.side_effect = [
        _resp(200, youtube_api_v3_video_response),
        _resp(200, youtube_api_v3_channel_response),
    ]

    mock_ytt = mock_ytt_class.return_value
    mock_ytt.fetch.side_effect = TranscriptsDisabled("dQw4w9WgXcQ")

    result = get_summary_data(VALID_URL)

    assert result.success is False
    assert result.error_code == ERROR_TRANSCRIPT_DISABLED
    assert result.title == "テスト動画タイトル"
    assert result.transcript is None


# --- Y-15: 異常系 IPブロック（RequestBlocked） ---

@patch("app.services.youtube.requests.get")
@patch("app.services.youtube.YouTubeTranscriptApi")
def test_y15_request_blocked(mock_ytt_class, mock_requests_get, youtube_api_v3_video_response, youtube_api_v3_channel_response):
    """RequestBlocked → success=False, error_code=RATE_LIMITED"""
    from youtube_transcript_api import RequestBlocked

    mock_requests_get.side_effect = [
        _resp(200, youtube_api_v3_video_response),
        _resp(200, youtube_api_v3_channel_response),
    ]

    mock_ytt = mock_ytt_class.return_value
    mock_ytt.fetch.side_effect = RequestBlocked("dQw4w9WgXcQ")

    result = get_summary_data(VALID_URL)

    assert result.success is False
    assert result.error_code == ERROR_RATE_LIMITED
    assert result.message == MSG_RATE_LIMITED


# --- Y-16: 異常系 oEmbedタイムアウト/非JSONレスポンス ---

@patch("app.services.youtube.time.sleep")
@patch("app.services.youtube.requests.get")
@patch("app.services.youtube.YouTubeTranscriptApi")
def test_y16_oembed_timeout(mock_ytt_class, mock_requests_get, mock_sleep, transcript_fetched_mock):
    """v3リトライ枯渇 + oEmbed タイムアウト → 字幕取得結果によるsuccess判定"""
    from requests.exceptions import Timeout

    retry_resp = _resp(503, {})
    mock_requests_get.side_effect = [retry_resp, retry_resp, retry_resp, retry_resp, Timeout("Connection timed out")]

    mock_ytt = mock_ytt_class.return_value
    mock_ytt.fetch.return_value = transcript_fetched_mock

    result = get_summary_data(VALID_URL)

    # 字幕は取れたので success=True, ただしメタデータは全てnull
    assert result.success is True
    assert result.error_code == ERROR_METADATA_FAILED
    assert result.title is None
    assert result.channel_name is None
    assert result.transcript is not None
    assert mock_sleep.call_args_list == [call(1), call(2), call(4)]


# --- Y-17: video_id 正規表現の境界値テスト ---

@pytest.mark.parametrize("url,expected_id", [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/v/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=120", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/watch?list=PLxxx&v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://example.com/video", None),
    ("not a url", None),
])
def test_y17_video_id_extraction(url, expected_id):
    """様々なURL形式から正しくvideo_idが抽出される/されない"""
    assert _extract_video_id(url) == expected_id


# --- Y-18: ISO 8601 duration を秒数に変換 ---

@pytest.mark.parametrize("input_str,expected", [
    ("PT1H2M3S", 3723),
    ("PT30S", 30),
    ("PT10M", 600),
    ("P0D", 0),
    ("PT0S", 0),
    ("P1DT2H3M4S", 93784),
    (None, None),
    ("", None),
])
def test_y18_parse_iso8601_duration(input_str, expected):
    """ISO 8601 duration を仕様どおり秒数に変換する。"""
    assert _parse_iso8601_duration(input_str) == expected


# --- Y-19: 秒数を duration 文字列に変換 ---

@pytest.mark.parametrize("seconds,expected", [
    (3723, "1:02:03"),
    (30, "0:30"),
    (600, "10:00"),
    (0, "0:00"),
    (93784, "26:03:04"),
    (None, None),
])
def test_y19_format_duration_string(seconds, expected):
    """秒数を H:MM:SS または M:SS に変換する。"""
    assert _format_duration_string(seconds) == expected


# --- Y-20: サムネイル優先順位選択 ---

@pytest.mark.parametrize("thumbnails,expected_url", [
    (
        {
            "maxres": {"url": "maxres_url"},
            "standard": {"url": "std_url"},
            "high": {"url": "high_url"},
            "medium": {"url": "med_url"},
            "default": {"url": "def_url"},
        },
        "maxres_url",
    ),
    (
        {
            "standard": {"url": "std_url"},
            "high": {"url": "high_url"},
            "medium": {"url": "med_url"},
            "default": {"url": "def_url"},
        },
        "std_url",
    ),
    (
        {
            "high": {"url": "high_url"},
            "medium": {"url": "med_url"},
            "default": {"url": "def_url"},
        },
        "high_url",
    ),
    (
        {
            "medium": {"url": "med_url"},
            "default": {"url": "def_url"},
        },
        "med_url",
    ),
    ({}, None),
    (None, None),
])
def test_y20_select_best_thumbnail(thumbnails, expected_url):
    """優先順 maxres -> standard -> high -> medium -> default を守って選択する。"""
    assert _select_best_thumbnail(thumbnails) == expected_url


# --- Y-22: API エラー分類 ---

@pytest.mark.parametrize("status_code,reason,expected_error_code", [
    (400, "badRequest", ERROR_INTERNAL),
    (401, "unauthorized", ERROR_INTERNAL),
    (403, "quotaExceeded", ERROR_RATE_LIMITED),
    (403, "forbidden", ERROR_VIDEO_NOT_FOUND),
    (403, "accessNotConfigured", ERROR_INTERNAL),
    (403, "otherReason", ERROR_INTERNAL),
    (404, "notFound", ERROR_VIDEO_NOT_FOUND),
    (429, None, ERROR_INTERNAL),
    (418, None, ERROR_INTERNAL),
])
def test_y22_classify_api_error(status_code, reason, expected_error_code):
    """HTTP status と reason を error_code に正しく変換する。"""
    error_body = {"error": {"errors": [{"reason": reason}]}} if reason else None
    assert _classify_api_error(status_code, error_body) == expected_error_code


# --- Y-23: 503 -> 200 のリトライ成功 ---

@patch("app.services.youtube.time.sleep")
@patch("app.services.youtube.requests.get")
def test_y23_retry_then_success(mock_get, mock_sleep):
    """503 の後に 200 が返ると再試行して成功する。"""
    url = "https://www.googleapis.com/youtube/v3/videos"
    params = {"id": "dQw4w9WgXcQ", "key": "test-youtube-api-key"}

    first_response = MagicMock()
    first_response.status_code = 503
    first_response.json.return_value = {}

    second_response = MagicMock()
    second_response.status_code = 200
    second_response.json.return_value = {"items": [{"id": "dQw4w9WgXcQ"}]}

    mock_get.side_effect = [first_response, second_response]

    result = _call_youtube_api_with_retry(url, params)

    assert result.data == {"items": [{"id": "dQw4w9WgXcQ"}]}
    assert result.error_code is None
    assert result.is_retryable_failure is False
    assert mock_get.call_count == 2
    mock_sleep.assert_called_once_with(1)


# --- Y-24: 全リトライ失敗 ---

@patch("app.services.youtube.time.sleep")
@patch("app.services.youtube.requests.get")
def test_y24_all_retries_exhausted(mock_get, mock_sleep):
    """503 が継続する場合は最大回数までリトライし、retryable failure を返す。"""
    url = "https://www.googleapis.com/youtube/v3/videos"
    params = {"id": "dQw4w9WgXcQ", "key": "test-youtube-api-key"}

    response = MagicMock()
    response.status_code = 503
    response.json.return_value = {}
    mock_get.return_value = response

    result = _call_youtube_api_with_retry(url, params)

    assert result.data is None
    assert result.error_code is None
    assert result.is_retryable_failure is True
    assert mock_get.call_count == 4
    assert mock_sleep.call_args_list == [call(1), call(2), call(4)]


# --- Y-25: 4xx はリトライしない ---

@patch("app.services.youtube.time.sleep")
@patch("app.services.youtube.requests.get")
def test_y25_4xx_no_retry(mock_get, mock_sleep, youtube_api_v3_quota_error):
    """403 quotaExceeded はリトライせず RATE_LIMITED を返す。"""
    url = "https://www.googleapis.com/youtube/v3/videos"
    params = {"id": "dQw4w9WgXcQ", "key": "test-youtube-api-key"}

    response = MagicMock()
    response.status_code = 403
    response.json.return_value = youtube_api_v3_quota_error
    mock_get.return_value = response

    result = _call_youtube_api_with_retry(url, params)

    assert result.data is None
    assert result.error_code == ERROR_RATE_LIMITED
    assert result.is_retryable_failure is False
    mock_get.assert_called_once()
    mock_sleep.assert_not_called()


# --- Y-25b: ログに API キーを出さない ---

@patch("app.services.youtube.requests.get")
def test_y25b_no_api_key_in_logs(mock_get, caplog, youtube_api_v3_quota_error):
    """エラーログに API キーや key= クエリ文字列を含めない。"""
    url = "https://www.googleapis.com/youtube/v3/videos"
    api_key = "test-youtube-api-key"
    params = {"id": "dQw4w9WgXcQ", "key": api_key}

    response = MagicMock()
    response.status_code = 403
    response.json.return_value = youtube_api_v3_quota_error
    mock_get.return_value = response

    with caplog.at_level(logging.WARNING):
        _call_youtube_api_with_retry(url, params)

    assert api_key not in caplog.text
    assert "key=" not in caplog.text


# --- Y-25c: ネットワーク例外 -> リトライ -> 成功 ---

@patch("app.services.youtube.time.sleep")
@patch("app.services.youtube.requests.get")
def test_y25c_network_error_retry_then_success(mock_get, mock_sleep):
    """RequestException 後に 200 が返ると再試行して成功する。"""
    from requests.exceptions import ConnectionError

    url = "https://www.googleapis.com/youtube/v3/videos"
    params = {"id": "dQw4w9WgXcQ", "key": "test-youtube-api-key"}

    success_response = MagicMock()
    success_response.status_code = 200
    success_response.json.return_value = {"items": [{"id": "dQw4w9WgXcQ"}]}

    mock_get.side_effect = [ConnectionError("Connection refused"), success_response]

    result = _call_youtube_api_with_retry(url, params)

    assert result.data == {"items": [{"id": "dQw4w9WgXcQ"}]}
    assert result.error_code is None
    assert result.is_retryable_failure is False
    assert mock_get.call_count == 2
    mock_sleep.assert_called_once_with(1)


# --- Y-25d: ネットワーク例外 x 4 -> 全リトライ失敗 ---

@patch("app.services.youtube.time.sleep")
@patch("app.services.youtube.requests.get")
def test_y25d_network_error_all_retries_exhausted(mock_get, mock_sleep):
    """RequestException が継続する場合は retryable failure を返す。"""
    from requests.exceptions import ConnectionError

    url = "https://www.googleapis.com/youtube/v3/videos"
    params = {"id": "dQw4w9WgXcQ", "key": "test-youtube-api-key"}

    mock_get.side_effect = ConnectionError("Connection refused")

    result = _call_youtube_api_with_retry(url, params)

    assert result.data is None
    assert result.error_code is None
    assert result.is_retryable_failure is True
    assert mock_get.call_count == 4
    assert mock_sleep.call_args_list == [call(1), call(2), call(4)]


# --- Y-21: categoryId の変換 ---

@pytest.mark.parametrize("category_id,expected", [
    ("27", ["Education"]),
    ("10", ["Music"]),
    ("999", ["999"]),
    (None, None),
])
def test_y21_category_conversion(category_id, expected):
    """categoryId を YOUTUBE_CATEGORY_MAP で変換し list[str] で返す。"""
    video_data = {
        "snippet": {
            "title": "title",
            "channelTitle": "channel",
            "channelId": "UC123",
            "publishedAt": "2026-02-08T10:00:00Z",
            "thumbnails": {"default": {"url": "https://example.com/thumb.jpg"}},
            "categoryId": category_id,
        },
        "contentDetails": {"duration": "PT1M"},
        "statistics": {"viewCount": "100"},
    }

    metadata = _build_metadata_from_youtube_api(video_data, None, "dQw4w9WgXcQ")
    assert metadata["categories"] == expected


# --- Y-26: videos.list + channels.list 正常系 ---

@patch("app.services.youtube._call_youtube_api_with_retry")
def test_y26_fetch_metadata_success(mock_call_api, youtube_api_v3_video_response, youtube_api_v3_channel_response):
    """videos.list と channels.list が成功した場合、metadata が構築される。"""
    mock_call_api.side_effect = [
        ApiCallResult(data=youtube_api_v3_video_response, error_code=None, is_retryable_failure=False),
        ApiCallResult(data=youtube_api_v3_channel_response, error_code=None, is_retryable_failure=False),
    ]

    result = _fetch_metadata_youtube_api("dQw4w9WgXcQ")

    assert result.error_code is None
    assert result.should_fallback is False
    assert result.metadata is not None
    assert result.metadata["title"] == "テスト動画タイトル"
    assert result.metadata["channel_follower_count"] == 1250000


# --- Y-27: items 空 ---

@patch("app.services.youtube._call_youtube_api_with_retry")
def test_y27_video_not_found(mock_call_api, youtube_api_v3_empty_response):
    """videos.list が items=[] を返した場合は VIDEO_NOT_FOUND。"""
    mock_call_api.return_value = ApiCallResult(
        data=youtube_api_v3_empty_response,
        error_code=None,
        is_retryable_failure=False,
    )

    result = _fetch_metadata_youtube_api("dQw4w9WgXcQ")

    assert result.metadata is None
    assert result.error_code == ERROR_VIDEO_NOT_FOUND
    assert result.should_fallback is False


# --- Y-28: quotaExceeded ---

@patch("app.services.youtube._call_youtube_api_with_retry")
def test_y28_quota_exceeded(mock_call_api):
    """videos.list で quotaExceeded が返った場合は RATE_LIMITED。"""
    mock_call_api.return_value = ApiCallResult(
        data=None,
        error_code=ERROR_RATE_LIMITED,
        is_retryable_failure=False,
    )

    result = _fetch_metadata_youtube_api("dQw4w9WgXcQ")

    assert result.metadata is None
    assert result.error_code == ERROR_RATE_LIMITED
    assert result.should_fallback is False


# --- Y-29: channels.list 失敗時の部分成功 ---

@patch("app.services.youtube._call_youtube_api_with_retry")
def test_y29_channels_partial_success(mock_call_api, youtube_api_v3_video_response):
    """channels.list が失敗しても metadata 構築は成功し、subscriber は None。"""
    mock_call_api.side_effect = [
        ApiCallResult(data=youtube_api_v3_video_response, error_code=None, is_retryable_failure=False),
        ApiCallResult(data=None, error_code=ERROR_INTERNAL, is_retryable_failure=False),
    ]

    result = _fetch_metadata_youtube_api("dQw4w9WgXcQ")

    assert result.error_code is None
    assert result.should_fallback is False
    assert result.metadata is not None
    assert result.metadata["channel_follower_count"] is None


# --- Y-30: YOUTUBE_API_KEY 未設定（単体） ---

@patch("app.services.youtube._call_youtube_api_with_retry")
def test_y30_api_key_not_set(mock_call_api, monkeypatch):
    """YOUTUBE_API_KEY 未設定時は fail-fast で INTERNAL_ERROR を返す。"""
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)

    result = _fetch_metadata_youtube_api("dQw4w9WgXcQ")

    assert result.metadata is None
    assert result.error_code == ERROR_INTERNAL
    assert result.should_fallback is False
    mock_call_api.assert_not_called()


# --- Y-30b: YOUTUBE_API_KEY 未設定（統合: 短絡終了） ---

@patch("app.services.youtube.requests.get")
@patch("app.services.youtube.YouTubeTranscriptApi")
def test_y30b_api_key_not_set_no_transcript_call(mock_ytt_class, mock_get, monkeypatch):
    """APIキー未設定時は字幕取得・oEmbedに進まず即時エラー返却する。"""
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)

    result = get_summary_data(VALID_URL)

    assert result.success is False
    assert result.error_code == ERROR_INTERNAL
    mock_get.assert_not_called()
    mock_ytt_class.return_value.fetch.assert_not_called()


# --- Y-31: quotaExceeded の message 分岐 ---

@patch("app.services.youtube.requests.get")
@patch("app.services.youtube.YouTubeTranscriptApi")
def test_y31_quota_exceeded_message(mock_ytt_class, mock_get, youtube_api_v3_quota_error):
    """quotaExceeded は短絡終了し MSG_QUOTA_EXCEEDED を返す。"""
    quota_response = MagicMock()
    quota_response.status_code = 403
    quota_response.json.return_value = youtube_api_v3_quota_error
    mock_get.return_value = quota_response

    result = get_summary_data(VALID_URL)

    assert result.success is False
    assert result.error_code == ERROR_RATE_LIMITED
    assert result.message == MSG_QUOTA_EXCEEDED
    assert mock_get.call_count == 1
    mock_ytt_class.return_value.fetch.assert_not_called()


# --- Y-32: 5xx 枯渇 -> oEmbed フォールバック ---

@patch("app.services.youtube.time.sleep")
@patch("app.services.youtube.requests.get")
@patch("app.services.youtube.YouTubeTranscriptApi")
def test_y32_5xx_fallback_to_oembed(
    mock_ytt_class,
    mock_get,
    mock_sleep,
    oembed_success_json,
    transcript_fetched_mock,
):
    """videos.list のリトライ枯渇後に oEmbed へフォールバックし、字幕成功なら METADATA_FAILED。"""
    retry_response = MagicMock()
    retry_response.status_code = 503
    retry_response.json.return_value = {}

    oembed_response = MagicMock()
    oembed_response.status_code = 200
    oembed_response.json.return_value = oembed_success_json
    oembed_response.raise_for_status.return_value = None

    mock_get.side_effect = [retry_response, retry_response, retry_response, retry_response, oembed_response]

    mock_ytt = mock_ytt_class.return_value
    mock_ytt.fetch.return_value = transcript_fetched_mock

    result = get_summary_data(VALID_URL)

    assert result.success is True
    assert result.error_code == ERROR_METADATA_FAILED
    assert result.title == "テスト動画タイトル"
    assert mock_get.call_count == 5
    assert mock_sleep.call_args_list == [call(1), call(2), call(4)]
