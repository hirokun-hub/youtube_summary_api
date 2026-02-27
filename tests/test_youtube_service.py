"""テストケース Y-1〜Y-17: サービス層の単体テスト（モック使用）"""

from unittest.mock import patch, MagicMock

import pytest

from app.core.constants import (
    ERROR_INTERNAL,
    ERROR_INVALID_URL,
    ERROR_METADATA_FAILED,
    ERROR_RATE_LIMITED,
    ERROR_TRANSCRIPT_DISABLED,
    ERROR_TRANSCRIPT_NOT_FOUND,
    ERROR_VIDEO_NOT_FOUND,
    MSG_SUCCESS,
    TRANSCRIPT_LANGUAGES,
)
from app.services.youtube import (
    _extract_video_id,
    _format_duration_string,
    _parse_iso8601_duration,
    _select_best_thumbnail,
    get_summary_data,
)


VALID_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


# --- Y-1: 正常系 全データ取得成功 ---

@patch("app.services.youtube.YouTubeTranscriptApi")
@patch("app.services.youtube.yt_dlp.YoutubeDL")
def test_y1_success_all_data(mock_ydl_class, mock_ytt_class,
                              ytdlp_success_info, transcript_fetched_mock):
    """yt-dlp成功 + transcript成功 → success=True, 全フィールドに値, oEmbed呼び出しなし"""
    # yt-dlp mock
    mock_ydl = mock_ydl_class.return_value.__enter__.return_value
    mock_ydl.extract_info.return_value = ytdlp_success_info
    mock_ydl.sanitize_info.return_value = ytdlp_success_info

    # transcript mock
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


# --- Y-2: 正常系 yt-dlp失敗→oEmbedフォールバック + transcript成功 ---

@patch("app.services.youtube.requests.get")
@patch("app.services.youtube.YouTubeTranscriptApi")
@patch("app.services.youtube.yt_dlp.YoutubeDL")
def test_y2_ytdlp_fallback_oembed(mock_ydl_class, mock_ytt_class, mock_requests_get,
                                    oembed_success_json, transcript_fetched_mock):
    """yt-dlp DownloadError + oEmbed成功 + transcript成功 → success=True, yt-dlp由来フィールドはnull"""
    from yt_dlp.utils import DownloadError

    # yt-dlp fails
    mock_ydl = mock_ydl_class.return_value.__enter__.return_value
    mock_ydl.extract_info.side_effect = DownloadError("Video not available")

    # oEmbed succeeds
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = oembed_success_json
    mock_resp.raise_for_status.return_value = None
    mock_requests_get.return_value = mock_resp

    # transcript succeeds
    mock_ytt = mock_ytt_class.return_value
    mock_ytt.fetch.return_value = transcript_fetched_mock

    result = get_summary_data(VALID_URL)

    assert result.success is True
    assert result.title == "テスト動画タイトル"
    assert result.channel_name == "テストチャンネル"
    assert result.thumbnail_url == "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"
    # yt-dlp由来のフィールドはnull
    assert result.upload_date is None
    assert result.duration is None
    assert result.view_count is None


# --- Y-3: 異常系 字幕なし + メタデータ成功 ---

@patch("app.services.youtube.YouTubeTranscriptApi")
@patch("app.services.youtube.yt_dlp.YoutubeDL")
def test_y3_no_transcript(mock_ydl_class, mock_ytt_class, ytdlp_success_info):
    """yt-dlp成功 + NoTranscriptFound → success=False, error_code=TRANSCRIPT_NOT_FOUND, メタデータあり"""
    from youtube_transcript_api import NoTranscriptFound

    mock_ydl = mock_ydl_class.return_value.__enter__.return_value
    mock_ydl.extract_info.return_value = ytdlp_success_info
    mock_ydl.sanitize_info.return_value = ytdlp_success_info

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
@patch("app.services.youtube.yt_dlp.YoutubeDL")
def test_y4_video_not_found(mock_ydl_class, mock_ytt_class, mock_requests_get):
    """yt-dlp DownloadError + oEmbed 404 + 字幕失敗 → success=False, error_code=VIDEO_NOT_FOUND"""
    from yt_dlp.utils import DownloadError
    from requests.exceptions import HTTPError
    from youtube_transcript_api import NoTranscriptFound

    mock_ydl = mock_ydl_class.return_value.__enter__.return_value
    mock_ydl.extract_info.side_effect = DownloadError("Video unavailable")

    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.raise_for_status.side_effect = HTTPError(response=mock_resp)
    mock_requests_get.return_value = mock_resp

    mock_ytt = mock_ytt_class.return_value
    mock_ytt.fetch.side_effect = NoTranscriptFound("dQw4w9WgXcQ", ["ja", "en"], {})

    result = get_summary_data(VALID_URL)

    assert result.success is False
    assert result.error_code == ERROR_VIDEO_NOT_FOUND
    assert result.title is None


# --- Y-5: 異常系 無効なURL ---

def test_y5_invalid_url():
    """無効なURL → success=False, error_code=INVALID_URL"""
    result = get_summary_data("https://example.com/not-a-youtube-video")

    assert result.success is False
    assert result.error_code == ERROR_INVALID_URL
    assert result.title is None
    assert result.transcript is None


# --- Y-6: 異常系 レート制限（YouTubeRequestFailed） ---

@patch("app.services.youtube.YouTubeTranscriptApi")
@patch("app.services.youtube.yt_dlp.YoutubeDL")
def test_y6_rate_limited(mock_ydl_class, mock_ytt_class, ytdlp_success_info):
    """YouTubeRequestFailed → success=False, error_code=RATE_LIMITED"""
    from youtube_transcript_api import YouTubeRequestFailed

    mock_ydl = mock_ydl_class.return_value.__enter__.return_value
    mock_ydl.extract_info.return_value = ytdlp_success_info
    mock_ydl.sanitize_info.return_value = ytdlp_success_info

    mock_ytt = mock_ytt_class.return_value
    mock_http_error = MagicMock()
    mock_ytt.fetch.side_effect = YouTubeRequestFailed("dQw4w9WgXcQ", mock_http_error)

    result = get_summary_data(VALID_URL)

    assert result.success is False
    assert result.error_code == ERROR_RATE_LIMITED


# --- Y-7: 異常系 予期せぬエラー ---

@patch("app.services.youtube.YouTubeTranscriptApi")
@patch("app.services.youtube.yt_dlp.YoutubeDL")
def test_y7_internal_error(mock_ydl_class, mock_ytt_class, ytdlp_success_info):
    """任意のException → success=False, error_code=INTERNAL_ERROR"""
    mock_ydl = mock_ydl_class.return_value.__enter__.return_value
    mock_ydl.extract_info.return_value = ytdlp_success_info
    mock_ydl.sanitize_info.return_value = ytdlp_success_info

    mock_ytt = mock_ytt_class.return_value
    mock_ytt.fetch.side_effect = RuntimeError("unexpected")

    result = get_summary_data(VALID_URL)

    assert result.success is False
    assert result.error_code == ERROR_INTERNAL


# --- Y-8: 安定性中フィールドの欠損 ---

@patch("app.services.youtube.YouTubeTranscriptApi")
@patch("app.services.youtube.yt_dlp.YoutubeDL")
def test_y8_missing_optional_fields(mock_ydl_class, mock_ytt_class,
                                     ytdlp_success_info, transcript_fetched_mock):
    """yt-dlp成功だが like_count=None, channel_follower_count=None → success=True, 該当フィールドがnull"""
    info = {**ytdlp_success_info}
    del info["like_count"]
    del info["channel_follower_count"]

    mock_ydl = mock_ydl_class.return_value.__enter__.return_value
    mock_ydl.extract_info.return_value = info
    mock_ydl.sanitize_info.return_value = info

    mock_ytt = mock_ytt_class.return_value
    mock_ytt.fetch.return_value = transcript_fetched_mock

    result = get_summary_data(VALID_URL)

    assert result.success is True
    assert result.like_count is None
    assert result.channel_follower_count is None
    assert result.title == "テスト動画タイトル"


# --- Y-9: transcript_language と is_generated の取得 ---

@patch("app.services.youtube.YouTubeTranscriptApi")
@patch("app.services.youtube.yt_dlp.YoutubeDL")
def test_y9_transcript_metadata(mock_ydl_class, mock_ytt_class,
                                 ytdlp_success_info, transcript_fetched_mock):
    """FetchedTranscript.language_code と FetchedTranscript.is_generated が正しく設定される"""
    mock_ydl = mock_ydl_class.return_value.__enter__.return_value
    mock_ydl.extract_info.return_value = ytdlp_success_info
    mock_ydl.sanitize_info.return_value = ytdlp_success_info

    mock_ytt = mock_ytt_class.return_value
    mock_ytt.fetch.return_value = transcript_fetched_mock

    result = get_summary_data(VALID_URL)

    assert result.transcript_language == "ja"
    assert result.is_generated is False


# --- Y-10: yt-dlp DownloadError → error_code マッピング ---

@patch("app.services.youtube.requests.get")
@patch("app.services.youtube.YouTubeTranscriptApi")
@patch("app.services.youtube.yt_dlp.YoutubeDL")
def test_y10_metadata_failed(mock_ydl_class, mock_ytt_class, mock_requests_get,
                              oembed_success_json, transcript_fetched_mock):
    """yt-dlp DownloadError + transcript成功 → error_code=METADATA_FAILED, success=True"""
    from yt_dlp.utils import DownloadError

    mock_ydl = mock_ydl_class.return_value.__enter__.return_value
    mock_ydl.extract_info.side_effect = DownloadError("Temporary error")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = oembed_success_json
    mock_resp.raise_for_status.return_value = None
    mock_requests_get.return_value = mock_resp

    mock_ytt = mock_ytt_class.return_value
    mock_ytt.fetch.return_value = transcript_fetched_mock

    result = get_summary_data(VALID_URL)

    assert result.success is True
    assert result.error_code == ERROR_METADATA_FAILED


# --- Y-11: transcript の後方互換性 ---

@patch("app.services.youtube.YouTubeTranscriptApi")
@patch("app.services.youtube.yt_dlp.YoutubeDL")
def test_y11_transcript_format(mock_ydl_class, mock_ytt_class,
                                ytdlp_success_info, transcript_fetched_mock):
    """transcriptフォーマットが [HH:MM:SS] テキスト のタイムスタンプ付き"""
    mock_ydl = mock_ydl_class.return_value.__enter__.return_value
    mock_ydl.extract_info.return_value = ytdlp_success_info
    mock_ydl.sanitize_info.return_value = ytdlp_success_info

    mock_ytt = mock_ytt_class.return_value
    mock_ytt.fetch.return_value = transcript_fetched_mock

    result = get_summary_data(VALID_URL)

    lines = result.transcript.split("\n")
    assert lines[0] == "[00:00:00] こんにちは"
    assert lines[1] == "[00:00:01] テストです"
    # 3661秒 = 1時間1分1秒
    assert lines[2] == "[01:01:01] 終わりです"


# --- Y-12: yt-dlp戻り値にキーが存在しない場合 ---

@patch("app.services.youtube.YouTubeTranscriptApi")
@patch("app.services.youtube.yt_dlp.YoutubeDL")
def test_y12_ytdlp_missing_keys(mock_ydl_class, mock_ytt_class, transcript_fetched_mock):
    """yt-dlp成功だがキーが部分的に欠損 → 該当フィールドがnull, エラーにならない"""
    minimal_info = {
        "title": "最小限の動画",
        "channel": "最小チャンネル",
    }

    mock_ydl = mock_ydl_class.return_value.__enter__.return_value
    mock_ydl.extract_info.return_value = minimal_info
    mock_ydl.sanitize_info.return_value = minimal_info

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

@patch("app.services.youtube.YouTubeTranscriptApi")
@patch("app.services.youtube.yt_dlp.YoutubeDL")
def test_y14_transcripts_disabled(mock_ydl_class, mock_ytt_class, ytdlp_success_info):
    """TranscriptsDisabled → success=False, error_code=TRANSCRIPT_DISABLED, メタデータあり"""
    from youtube_transcript_api import TranscriptsDisabled

    mock_ydl = mock_ydl_class.return_value.__enter__.return_value
    mock_ydl.extract_info.return_value = ytdlp_success_info
    mock_ydl.sanitize_info.return_value = ytdlp_success_info

    mock_ytt = mock_ytt_class.return_value
    mock_ytt.fetch.side_effect = TranscriptsDisabled("dQw4w9WgXcQ")

    result = get_summary_data(VALID_URL)

    assert result.success is False
    assert result.error_code == ERROR_TRANSCRIPT_DISABLED
    assert result.title == "テスト動画タイトル"
    assert result.transcript is None


# --- Y-15: 異常系 IPブロック（RequestBlocked） ---

@patch("app.services.youtube.YouTubeTranscriptApi")
@patch("app.services.youtube.yt_dlp.YoutubeDL")
def test_y15_request_blocked(mock_ydl_class, mock_ytt_class, ytdlp_success_info):
    """RequestBlocked → success=False, error_code=RATE_LIMITED"""
    from youtube_transcript_api import RequestBlocked

    mock_ydl = mock_ydl_class.return_value.__enter__.return_value
    mock_ydl.extract_info.return_value = ytdlp_success_info
    mock_ydl.sanitize_info.return_value = ytdlp_success_info

    mock_ytt = mock_ytt_class.return_value
    mock_ytt.fetch.side_effect = RequestBlocked("dQw4w9WgXcQ")

    result = get_summary_data(VALID_URL)

    assert result.success is False
    assert result.error_code == ERROR_RATE_LIMITED


# --- Y-16: 異常系 oEmbedタイムアウト/非JSONレスポンス ---

@patch("app.services.youtube.requests.get")
@patch("app.services.youtube.YouTubeTranscriptApi")
@patch("app.services.youtube.yt_dlp.YoutubeDL")
def test_y16_oembed_timeout(mock_ydl_class, mock_ytt_class, mock_requests_get,
                             transcript_fetched_mock):
    """yt-dlp DownloadError + oEmbed タイムアウト → 字幕取得結果によるsuccess判定"""
    from yt_dlp.utils import DownloadError
    from requests.exceptions import Timeout

    mock_ydl = mock_ydl_class.return_value.__enter__.return_value
    mock_ydl.extract_info.side_effect = DownloadError("error")

    mock_requests_get.side_effect = Timeout("Connection timed out")

    mock_ytt = mock_ytt_class.return_value
    mock_ytt.fetch.return_value = transcript_fetched_mock

    result = get_summary_data(VALID_URL)

    # 字幕は取れたので success=True, ただしメタデータは全てnull
    assert result.success is True
    assert result.title is None
    assert result.channel_name is None
    assert result.transcript is not None


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
