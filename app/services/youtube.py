# app/services/youtube.py

"""
このモジュールは、YouTubeに関連する外部APIとの連携や、
データ処理などのビジネスロジックを担当します。
"""

import logging
import re
import requests
import urllib.error
from urllib.parse import urlunparse
from requests.exceptions import HTTPError as RequestsHTTPError
from youtube_transcript_api import (
    YouTubeTranscriptApi,
    NoTranscriptFound,
    YouTubeTranscriptApiException,
    YouTubeRequestFailed,
)

from app.models.schemas import SummaryResponse

# このモジュール用のロガーを設定
logger = logging.getLogger(__name__)


def _extract_video_id(url: str) -> str | None:
    """
    様々な形式のYouTube URLから動画IDを抽出します。
    正規表現を使用して、標準、短縮、埋め込み形式のURLに対応します。

    Args:
        url: YouTubeのURL。

    Returns:
        抽出された動画ID。見つからない場合はNone。
    """
    # 参考: https://stackoverflow.com/a/7936523
    regex = r"(?:https?://)?(?:www\.)?(?:youtube\.com/(?:[^/\n\s]+/[\S]+/|(?:v|e(?:mbed)?)/|\S*?[?&]v=)|youtu\.be/)([a-zA-Z0-9_-]{11})"
    match = re.search(regex, url)
    if match:
        return match.group(1)
    return None


def get_summary_data(video_url: str) -> SummaryResponse:
    """
    指定されたYouTube動画URLからメタデータと文字起こしを取得し、
    SummaryResponseオブジェクトとして返します。
    エラーが発生した場合も、エラー情報を含んだSummaryResponseを返します。

    Args:
        video_url: YouTube動画のURL。

    Returns:
        SummaryResponse: 動画の情報と処理結果。
    """
    logger.info(f"動画情報の取得処理を開始: {video_url}")
    video_title = None
    channel_name = None

    try:
        # --- 1. URLから動画IDを抽出し、oEmbed APIでメタデータを取得 ---
        logger.debug("URLから動画IDを抽出中...")
        video_id = _extract_video_id(video_url)
        if not video_id:
            logger.warning(f"URLから動画IDを抽出できませんでした: {video_url}")
            return SummaryResponse(
                success=False,
                message="無効なYouTube動画URLです。有効なURL形式か確認してください。",
                title=None, channel_name=None, transcript=None
            )

        normalized_url = urlunparse(('https', 'www.youtube.com', '/watch', '', f'v={video_id}', ''))
        oembed_url = f"https://www.youtube.com/oembed?url={normalized_url}&format=json"
        meta_resp = requests.get(oembed_url, timeout=10)
        meta_resp.raise_for_status()
        meta_json = meta_resp.json()
        video_title = meta_json.get("title")
        channel_name = meta_json.get("author_name")
        logger.debug(f"動画タイトル: {video_title}, チャンネル名: {channel_name}")

        # --- 2. youtube-transcript-apiを使って文字起こしを取得 ---
        logger.debug(f"文字起こし取得を開始... (Video ID: {video_id})")
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['ja', 'en'])
        
        transcript_lines = [f"[{int(elem['start']//3600):02d}:{int(elem['start']%3600//60):02d}:{int(elem['start']%60):02d}] {elem['text']}" for elem in transcript_list]
        transcript_text = "\n".join(transcript_lines)
        logger.debug(f"文字起こしの取得に成功。文字数: {len(transcript_text)}")

        # --- 3. 成功レスポンスを組み立てる ---
        logger.info(f"処理成功: {video_title}")
        return SummaryResponse(
            success=True,
            message="Successfully retrieved data.",
            title=video_title,
            channel_name=channel_name,
            transcript=transcript_text
        )

    except NoTranscriptFound:
        logger.warning(f"文字起こしが見つかりませんでした: {video_url}")
        return SummaryResponse(
            success=False,
            message="この動画には利用可能な文字起こしがありませんでした。",
            title=video_title, channel_name=channel_name, transcript=None
        )
    except YouTubeRequestFailed as e:
        logger.error(f"YouTubeへのリクエストに失敗(429等): {video_url}", exc_info=True)
        return SummaryResponse(
            success=False,
            message=f"YouTubeへのリクエストが多すぎるため、一時的に情報を取得できません。時間をおいて再度お試しください。 Error: {e}",
            title=video_title, channel_name=channel_name, transcript=None
        )
    except (urllib.error.HTTPError, RequestsHTTPError) as http_err:
        logger.warning(f"YouTube oEmbed APIからHTTPエラー: {http_err}")
        return SummaryResponse(
            success=False,
            message=f"YouTubeから情報を取得できませんでした。動画が存在しないか、非公開の可能性があります。 Error: {http_err}",
            title=video_title, channel_name=channel_name, transcript=None
        )
    except Exception as e:
        logger.error(f"サービス層で予期せぬエラーが発生: {video_url}", exc_info=True)
        return SummaryResponse(
            success=False,
            message=f"内部処理中に予期せぬエラーが発生しました。 Error: {e}",
            title=video_title, channel_name=channel_name, transcript=None
        )
