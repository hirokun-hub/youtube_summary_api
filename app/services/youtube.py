# app/services/youtube.py

"""
このモジュールは、YouTubeに関連する外部APIとの連携や、
データ処理などのビジネスロジックを担当します。
"""

import logging
import time
import re
import requests
import yt_dlp
from urllib.parse import urlunparse
from typing import NamedTuple

from youtube_transcript_api import (
    YouTubeTranscriptApi,
    NoTranscriptFound,
    TranscriptsDisabled,
    YouTubeRequestFailed,
    RequestBlocked,
)

from app.models.schemas import SummaryResponse
from app.core.constants import (
    ERROR_CODE_TO_MESSAGE,
    ERROR_INTERNAL,
    ERROR_INVALID_URL,
    ERROR_METADATA_FAILED,
    ERROR_RATE_LIMITED,
    ERROR_TRANSCRIPT_DISABLED,
    ERROR_TRANSCRIPT_NOT_FOUND,
    ERROR_VIDEO_NOT_FOUND,
    MSG_INTERNAL_ERROR,
    MSG_INVALID_URL,
    MSG_METADATA_FAILED,
    MSG_SUCCESS,
    MSG_VIDEO_NOT_FOUND,
    OEMBED_TIMEOUT_SECONDS,
    OEMBED_URL_TEMPLATE,
    TRANSCRIPT_LANGUAGES,
    YOUTUBE_API_V3_MAX_RETRIES,
    YOUTUBE_API_V3_RETRY_BASE_DELAY,
    YOUTUBE_API_V3_RETRY_STATUS_CODES,
    YOUTUBE_API_V3_TIMEOUT,
    YOUTUBE_THUMBNAIL_PRIORITY,
    YTDLP_DIRECT_KEYS,
    YTDLP_KEY_MAP,
)

# このモジュール用のロガーを設定
logger = logging.getLogger(__name__)

_YT_REASON_QUOTA_EXCEEDED = "quotaExceeded"
_YT_REASON_FORBIDDEN = "forbidden"
_YT_REASON_ACCESS_NOT_CONFIGURED = "accessNotConfigured"


class ApiCallResult(NamedTuple):
    """単一 API 呼び出しの結果を表す。"""
    data: dict | None
    error_code: str | None
    is_retryable_failure: bool


def _extract_api_error_reason(error_body: dict | None) -> str | None:
    """YouTube Data API v3 のエラーレスポンスから reason を抽出する。"""
    if not isinstance(error_body, dict):
        return None
    errors = error_body.get("error", {}).get("errors", [])
    if errors and isinstance(errors[0], dict):
        return errors[0].get("reason")
    return None


def _classify_api_error(status_code: int, error_body: dict | None) -> str:
    """YouTube Data API v3 の 4xx エラーを内部 error_code に分類する。"""
    reason = _extract_api_error_reason(error_body)

    if status_code == 403:
        if reason == _YT_REASON_QUOTA_EXCEEDED:
            return ERROR_RATE_LIMITED
        if reason == _YT_REASON_FORBIDDEN:
            return ERROR_VIDEO_NOT_FOUND
        if reason == _YT_REASON_ACCESS_NOT_CONFIGURED:
            return ERROR_INTERNAL
        return ERROR_INTERNAL
    if status_code == 404:
        return ERROR_VIDEO_NOT_FOUND
    if 400 <= status_code < 500:
        return ERROR_INTERNAL
    return ERROR_INTERNAL


def _call_youtube_api_with_retry(url: str, params: dict) -> ApiCallResult:
    """YouTube Data API をリトライ付きで呼び出す。"""
    for attempt in range(YOUTUBE_API_V3_MAX_RETRIES + 1):
        try:
            response = requests.get(url, params=params, timeout=YOUTUBE_API_V3_TIMEOUT)
        except requests.exceptions.RequestException:
            if attempt >= YOUTUBE_API_V3_MAX_RETRIES:
                logger.warning("YouTube API request failed after retry exhaustion due to network error.")
                return ApiCallResult(data=None, error_code=None, is_retryable_failure=True)

            delay = YOUTUBE_API_V3_RETRY_BASE_DELAY * (2 ** attempt)
            logger.warning("YouTube API network error. retry_in=%s", delay)
            time.sleep(delay)
            continue

        if response.status_code == 200:
            try:
                return ApiCallResult(data=response.json(), error_code=None, is_retryable_failure=False)
            except ValueError:
                logger.error("YouTube API returned invalid JSON. status_code=200")
                return ApiCallResult(data=None, error_code=ERROR_INTERNAL, is_retryable_failure=False)

        if response.status_code in YOUTUBE_API_V3_RETRY_STATUS_CODES:
            if attempt >= YOUTUBE_API_V3_MAX_RETRIES:
                logger.warning(
                    "YouTube API retryable error persisted after retries. status_code=%s",
                    response.status_code,
                )
                return ApiCallResult(data=None, error_code=None, is_retryable_failure=True)

            delay = YOUTUBE_API_V3_RETRY_BASE_DELAY * (2 ** attempt)
            logger.warning(
                "YouTube API retryable error. status_code=%s retry_in=%s",
                response.status_code,
                delay,
            )
            time.sleep(delay)
            continue

        error_body = None
        try:
            error_body = response.json()
        except ValueError:
            error_body = None

        error_code = _classify_api_error(response.status_code, error_body)
        reason = _extract_api_error_reason(error_body)
        logger.warning(
            "YouTube API non-retryable error. status_code=%s reason=%s",
            response.status_code,
            reason,
        )
        return ApiCallResult(data=None, error_code=error_code, is_retryable_failure=False)

    # for ループ内の全パスで return/continue するためここには到達しない
    raise AssertionError("unreachable")  # pragma: no cover


def _parse_iso8601_duration(duration_str: str | None) -> int | None:
    """ISO 8601 duration 文字列を秒数に変換する。"""
    if not duration_str:
        return None

    match = re.fullmatch(
        r"P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?",
        duration_str,
    )
    if not match:
        return None

    days = match.group("days")
    hours = match.group("hours")
    minutes = match.group("minutes")
    seconds = match.group("seconds")
    if days is None and hours is None and minutes is None and seconds is None:
        return None

    total_seconds = 0
    total_seconds += int(days) * 86400 if days else 0
    total_seconds += int(hours) * 3600 if hours else 0
    total_seconds += int(minutes) * 60 if minutes else 0
    total_seconds += int(seconds) if seconds else 0
    return total_seconds


def _format_duration_string(total_seconds: int | None) -> str | None:
    """秒数を H:MM:SS または M:SS 形式に変換する。"""
    if total_seconds is None:
        return None

    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours >= 1:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _select_best_thumbnail(thumbnails: dict | None) -> str | None:
    """thumbnails dict から優先順位に従ってURLを1つ選ぶ。"""
    if not thumbnails:
        return None

    for key in YOUTUBE_THUMBNAIL_PRIORITY:
        candidate = thumbnails.get(key)
        if not isinstance(candidate, dict):
            continue
        url = candidate.get("url")
        if url:
            return url
    return None


def _extract_video_id(url: str) -> str | None:
    """
    様々な形式のYouTube URLから動画IDを抽出します。
    正規表現を使用して、標準、短縮、埋め込み形式のURLに対応します。
    """
    # 参考: https://stackoverflow.com/a/7936523 (shorts対応を追加)
    regex = r"(?:https?://)?(?:www\.)?(?:youtube\.com/(?:shorts/|[^/\n\s]+/[\S]+/|(?:v|e(?:mbed)?)/|\S*?[?&]v=)|youtu\.be/)([a-zA-Z0-9_-]{11})"
    match = re.search(regex, url)
    if match:
        return match.group(1)
    return None


def _fetch_metadata_ytdlp(video_url: str) -> dict | None:
    """yt-dlpでメタデータを一括取得する。失敗時はNoneを返す。"""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "socket_timeout": 30,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            info = ydl.sanitize_info(info)
            return info
    except Exception:
        logger.warning(f"yt-dlpによるメタデータ取得に失敗: {video_url}", exc_info=True)
        return None


def _fetch_metadata_oembed(video_id: str) -> dict | None:
    """oEmbed APIでフォールバック用の最低限メタデータを取得する。失敗時はNoneを返す。"""
    normalized_url = urlunparse(('https', 'www.youtube.com', '/watch', '', f'v={video_id}', ''))
    oembed_url = OEMBED_URL_TEMPLATE.format(url=normalized_url)
    try:
        resp = requests.get(oembed_url, timeout=OEMBED_TIMEOUT_SECONDS)
        resp.raise_for_status()
        data = resp.json()
        return {
            "title": data.get("title"),
            "channel_name": data.get("author_name"),
            "thumbnail_url": data.get("thumbnail_url"),
        }
    except Exception:
        logger.warning(f"oEmbed APIによるメタデータ取得にも失敗: video_id={video_id}")
        return None


def _convert_upload_date(raw: str | None) -> str | None:
    """yt-dlpのYYYYMMDD形式をISO 8601（YYYY-MM-DD）に変換する。"""
    if raw and len(raw) == 8:
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    return raw


def _build_metadata_from_ytdlp(info: dict) -> dict:
    """yt-dlpの戻り値からレスポンス用のメタデータdictを構築する。"""
    result = {}
    for ytdlp_key, response_field in YTDLP_KEY_MAP.items():
        result[response_field] = info.get(ytdlp_key)
    for key in YTDLP_DIRECT_KEYS:
        result[key] = info.get(key)
    result["upload_date"] = _convert_upload_date(result.get("upload_date"))
    return result


def get_summary_data(video_url: str) -> SummaryResponse:
    """
    指定されたYouTube動画URLからメタデータと文字起こしを取得し、
    SummaryResponseオブジェクトとして返します。

    処理順序:
    1. URLから動画IDを抽出
    2. yt-dlpでメタデータを取得（失敗時はoEmbedにフォールバック）
    3. youtube-transcript-apiで字幕を取得
    4. レスポンスを組み立てて返す
    """
    logger.info(f"動画情報の取得処理を開始: {video_url}")

    # --- 1. URLから動画IDを抽出 ---
    video_id = _extract_video_id(video_url)
    if not video_id:
        logger.warning(f"URLから動画IDを抽出できませんでした: {video_url}")
        return SummaryResponse(
            success=False,
            message=MSG_INVALID_URL,
            error_code=ERROR_INVALID_URL,
        )

    # --- 2. メタデータ取得（yt-dlp → oEmbed フォールバック） ---
    metadata = {}
    ytdlp_failed = False

    ytdlp_info = _fetch_metadata_ytdlp(video_url)
    if ytdlp_info is not None:
        metadata = _build_metadata_from_ytdlp(ytdlp_info)
    else:
        ytdlp_failed = True
        oembed_data = _fetch_metadata_oembed(video_id)
        if oembed_data is not None:
            metadata = oembed_data
        else:
            logger.warning(f"メタデータ取得に全て失敗: {video_url}")

    # --- 3. 字幕取得 ---
    transcript_text = None
    transcript_language = None
    is_generated = None
    transcript_error_code = None

    try:
        api = YouTubeTranscriptApi()
        fetched = api.fetch(video_id, languages=TRANSCRIPT_LANGUAGES)
        transcript_language = fetched.language_code
        is_generated = fetched.is_generated

        raw_data = fetched.to_raw_data()
        transcript_lines = [
            f"[{int(elem['start']//3600):02d}:{int(elem['start']%3600//60):02d}:{int(elem['start']%60):02d}] {elem['text']}"
            for elem in raw_data
        ]
        transcript_text = "\n".join(transcript_lines)
        logger.debug(f"文字起こし取得成功。文字数: {len(transcript_text)}")

    except NoTranscriptFound:
        logger.warning(f"字幕が見つかりませんでした: {video_url}")
        transcript_error_code = ERROR_TRANSCRIPT_NOT_FOUND
    except TranscriptsDisabled:
        logger.warning(f"字幕機能が無効化されています: {video_url}")
        transcript_error_code = ERROR_TRANSCRIPT_DISABLED
    except (YouTubeRequestFailed, RequestBlocked):
        logger.error(f"YouTubeへのリクエストがブロックされました: {video_url}")
        transcript_error_code = ERROR_RATE_LIMITED
    except Exception:
        logger.error(f"字幕取得中に予期せぬエラー: {video_url}", exc_info=True)
        transcript_error_code = ERROR_INTERNAL

    # --- 4. レスポンス組み立て ---
    success = transcript_text is not None
    if success:
        if ytdlp_failed:
            error_code = ERROR_METADATA_FAILED
            message = MSG_METADATA_FAILED
        else:
            error_code = None
            message = MSG_SUCCESS
    else:
        error_code = transcript_error_code
        message = ERROR_CODE_TO_MESSAGE.get(error_code, MSG_INTERNAL_ERROR)

        # メタデータもなければ VIDEO_NOT_FOUND
        if not metadata and ytdlp_failed:
            error_code = ERROR_VIDEO_NOT_FOUND
            message = MSG_VIDEO_NOT_FOUND

    return SummaryResponse(
        success=success,
        message=message,
        error_code=error_code,
        title=metadata.get("title"),
        channel_name=metadata.get("channel_name"),
        channel_id=metadata.get("channel_id"),
        channel_follower_count=metadata.get("channel_follower_count"),
        upload_date=metadata.get("upload_date"),
        duration=metadata.get("duration"),
        duration_string=metadata.get("duration_string"),
        view_count=metadata.get("view_count"),
        like_count=metadata.get("like_count"),
        thumbnail_url=metadata.get("thumbnail_url"),
        description=metadata.get("description"),
        tags=metadata.get("tags"),
        categories=metadata.get("categories"),
        webpage_url=metadata.get("webpage_url"),
        transcript=transcript_text,
        transcript_language=transcript_language,
        is_generated=is_generated,
    )
