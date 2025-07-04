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

from app.models.schemas import VideoResponse

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
    regex = r"(?:https?://)?(?:www\.)?(?:youtube\.com/(?:[^/\n\s]+/\S+/|(?:v|e(?:mbed)?)/|\S*?[?&]v=)|youtu\.be/)([a-zA-Z0-9_-]{11})"
    match = re.search(regex, url)
    if match:
        return match.group(1)
    return None


def get_video_details(video_url: str) -> VideoResponse:
    """
    指定されたYouTube動画URLからメタデータと文字起こしを取得し、
    VideoResponseオブジェクトとして返します。

    Args:
        video_url: YouTube動画のURL。

    Raises:
        ValueError: 無効なYouTube URLや内部処理エラーの場合。
        NoTranscriptFound: 文字起こしが見つからない場合。
        urllib.error.HTTPError: YouTube oEmbed APIからのHTTPエラー。
        RequestsHTTPError: YouTube oEmbed APIからのHTTPエラー。

    Returns:
        VideoResponse: 動画の詳細情報。
    """
    logger.info(f"動画情報の取得処理を開始: {video_url}")
    try:
        # --- 1. URLから動画IDを抽出し、oEmbed APIでメタデータを取得 ---
        logger.debug("URLから動画IDを抽出中...")
        video_id = _extract_video_id(video_url)
        if not video_id:
            logger.warning(f"URLから動画IDを抽出できませんでした: {video_url}")
            raise ValueError("無効なYouTube動画URLです。有効なURL形式か確認してください。")

        # 正規化されたURLを再構築（不要なパラメータを除外）
        normalized_url = urlunparse(('https', 'www.youtube.com', '/watch', '', f'v={video_id}', ''))
        logger.debug(f"正規化されたURL: {normalized_url}, 動画ID: {video_id}")

        # YouTubeのoEmbed APIを使って動画のメタデータを取得
        oembed_url = f"https://www.youtube.com/oembed?url={normalized_url}&format=json"
        logger.debug(f"oEmbed APIにリクエスト: {oembed_url}")
        # タイムアウトを設定して、外部APIの応答が遅い場合に無期限に待機するのを防ぐ
        meta_resp = requests.get(oembed_url, timeout=10)
        meta_resp.raise_for_status() # エラーがあればHTTPErrorを発生させる
        meta_json = meta_resp.json()
        video_title = meta_json.get("title", "(取得失敗)")
        channel_name = meta_json.get("author_name", "(取得失敗)")
        logger.debug(f"動画タイトル: {video_title}")

        # --- 2. youtube-transcript-apiを使って文字起こしを取得 ---
        logger.debug(f"youtube-transcript-apiによる文字起こし取得を開始... (Video ID: {video_id})")
        # 日本語、または英語の文字起こしを試みる
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['ja', 'en'])
        
        # 取得した文字起こしデータをタイムスタンプ付きで結合する内部関数
        def format_timestamp(seconds: float) -> str:
            """秒数を hh:mm:ss または mm:ss 形式に変換"""
            try:
                seconds = int(seconds)
                h = seconds // 3600
                m = (seconds % 3600) // 60
                s = seconds % 60
                if h > 0:
                    return f"{h:02d}:{m:02d}:{s:02d}"
                return f"{m:02d}:{s:02d}"
            except Exception:
                return "00:00"

        transcript_lines: list[str] = []
        for elem in transcript_list:
            try:
                start = elem.get("start", 0)
                text = elem.get("text", "")
                transcript_lines.append(f"[{format_timestamp(start)}] {text}")
            except Exception as e_item:
                logger.debug(f"文字起こし要素の解析に失敗: {e_item} | elem={elem}")
        transcript_text = "\n".join(transcript_lines)
        logger.debug(f"文字起こしの取得に成功。文字数: {len(transcript_text)}")

        # --- 3. レスポンスデータを組み立てる ---
        logger.debug("レスポンスデータの組み立てを開始...")
        response_data = VideoResponse(
            title=video_title,
            channel_name=channel_name,
            video_url=video_url,
            upload_date="N/A", # oEmbed APIでは提供されない
            view_count=0, # oEmbed APIでは提供されない
            like_count=None, # oEmbed APIでは提供されない
            subscriber_count=None, # oEmbed APIでは提供されない
            transcript=transcript_text
        )
        logger.info(f"処理成功: {video_title}")
        return response_data

    # 各種例外を補足し、呼び出し元（ルーター）に情報を伝播させる
    except (NoTranscriptFound, YouTubeTranscriptApiException) as yta_err:
        # youtube-transcript-api が投げる既知の例外はそのまま上位へ伝播させる
        logger.warning(f"youtube-transcript-api 例外を捕捉: {yta_err} | URL: {video_url}")
        raise
    
    except (urllib.error.HTTPError, RequestsHTTPError) as http_err:
        logger.warning(f"YouTube / oEmbed API から HTTPError が返されました: {http_err}")
        raise # 例外をそのまま再送出

    except Exception as e:
        # その他の予期せぬエラーは、ここで一般的なエラーとしてラップして再送出する
        logger.error(f"サービス層で予期せぬエラーが発生しました: {video_url}", exc_info=True)
        raise ValueError(f"内部処理中に予期せぬエラーが発生しました。") from e
