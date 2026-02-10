# app/services/youtube.py

"""
このモジュールは、YouTubeに関連する外部APIとの連携や、
データ処理などのビジネスロジックを担当します。
"""

import logging
import re
import requests
import yt_dlp
from urllib.parse import urlunparse

from youtube_transcript_api import (
    YouTubeTranscriptApi,
    NoTranscriptFound,
    TranscriptsDisabled,
    YouTubeRequestFailed,
    RequestBlocked,
)

from app.models.schemas import SummaryResponse
from app.core.constants import (
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
    MSG_RATE_LIMITED,
    MSG_SUCCESS,
    MSG_TRANSCRIPT_DISABLED,
    MSG_TRANSCRIPT_NOT_FOUND,
    MSG_VIDEO_NOT_FOUND,
    OEMBED_TIMEOUT_SECONDS,
    OEMBED_URL_TEMPLATE,
    TRANSCRIPT_LANGUAGES,
    YTDLP_DIRECT_KEYS,
    YTDLP_KEY_MAP,
)

# このモジュール用のロガーを設定
logger = logging.getLogger(__name__)


def _extract_video_id(url: str) -> str | None:
    """
    様々な形式のYouTube URLから動画IDを抽出します。
    正規表現を使用して、標準、短縮、埋め込み形式のURLに対応します。
    """
    # 参考: https://stackoverflow.com/a/7936523
    regex = r"(?:https?://)?(?:www\.)?(?:youtube\.com/(?:[^/\n\s]+/[\S]+/|(?:v|e(?:mbed)?)/|\S*?[?&]v=)|youtu\.be/)([a-zA-Z0-9_-]{11})"
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
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            info = ydl.sanitize_info(info)
            return info
    except yt_dlp.utils.DownloadError:
        logger.warning(f"yt-dlpによるメタデータ取得に失敗: {video_url}")
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


def _build_metadata_from_ytdlp(info: dict) -> dict:
    """yt-dlpの戻り値からレスポンス用のメタデータdictを構築する。"""
    result = {}
    for ytdlp_key, response_field in YTDLP_KEY_MAP.items():
        result[response_field] = info.get(ytdlp_key)
    for key in YTDLP_DIRECT_KEYS:
        result[key] = info.get(key)
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
        if error_code == ERROR_TRANSCRIPT_NOT_FOUND:
            message = MSG_TRANSCRIPT_NOT_FOUND
        elif error_code == ERROR_TRANSCRIPT_DISABLED:
            message = MSG_TRANSCRIPT_DISABLED
        elif error_code == ERROR_RATE_LIMITED:
            message = MSG_RATE_LIMITED
        elif error_code == ERROR_INTERNAL:
            message = MSG_INTERNAL_ERROR
        else:
            message = MSG_INTERNAL_ERROR

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
