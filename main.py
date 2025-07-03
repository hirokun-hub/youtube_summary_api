# 必要なライブラリをインポート
import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl
from pytube import YouTube
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound

# ---　ログ設定　---
# ログレベルを設定 (INFO, DEBUG, WARNING, ERROR, CRITICAL)
# この変数を変更することで、ログの詳細度を簡単に切り替え可能
LOG_LEVEL = "DEBUG"
logging.basicConfig(level=LOG_LEVEL, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ---　FastAPIアプリケーションのインスタンスを作成　---
# APIのドキュメントに表示される情報を設定
app = FastAPI(
    title="YouTube動画情報取得API",
    description="指定されたYouTube動画のメタデータと文字起こしを取得するAPIです。",
    version="1.0.0",
)

# ---　データモデルの定義 (Pydanticを使用)　---
# これにより、リクエストとレスポンスのデータ型が保証される

# リクエストボディの型を定義
class VideoRequest(BaseModel):
    """APIへのリクエストとして受け取るデータ構造を定義します。"""
    # HttpUrl型を使うことで、URLが正しい形式か自動でバリデーションされる
    url: HttpUrl

# レスポンスボディの型を定義
class VideoResponse(BaseModel):
    """APIからのレスポンスとして返すデータ構造を定義します。"""
    title: str
    channel_name: str
    video_url: str
    upload_date: str
    view_count: int
    # like_countとsubscriber_countはpytubeでは安定して取得できないため、オプショナル(None許容)とする
    like_count: int | None
    subscriber_count: int | None
    transcript: str

# ---　APIエンドポイントの定義　---

# ルートエンドポイント: APIが起動しているかを確認するための簡単なエンドポイント
@app.get("/")
def read_root():
    """APIのルートURLにアクセスした際に、ウェルカムメッセージを返します。"""
    logger.info("ルートエンドポイントへのアクセスがありました。")
    return {"message": "YouTube動画情報取得APIへようこそ"}

# 動画情報取得エンドポイント
@app.post("/api/v1/summary", response_model=VideoResponse)
def get_summary(request: VideoRequest):
    """
    YouTube動画のURLを受け取り、動画のメタデータと文字起こしを返します。

    - **request**: `VideoRequest`モデル。`url`キーにYouTubeのURLを含むJSON。
    - **return**: `VideoResponse`モデル。動画情報を含むJSON。
    """
    video_url = str(request.url)
    logger.info(f"処理開始: URL = {video_url}")

    try:
        # --- 1. pytubeを使って動画のメタデータを取得 ---
        logger.debug("pytubeによるメタデータ取得を開始...")
        yt = YouTube(video_url)
        logger.debug(f"動画タイトル: {yt.title}")

        # --- 2. youtube-transcript-apiを使って文字起こしを取得 ---
        video_id = yt.video_id
        logger.debug(f"youtube-transcript-apiによる文字起こし取得を開始... (Video ID: {video_id})")
        # 日本語、または英語の文字起こしを試みる
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['ja', 'en'])
        
        # 取得した文字起こしデータを一つの文字列に結合
        transcript_text = " ".join([item['text'] for item in transcript_list])
        logger.debug(f"文字起こしの取得に成功。文字数: {len(transcript_text)}")

        # --- 3. レスポンスデータを組み立てる ---
        logger.debug("レスポンスデータの組み立てを開始...")
        # pytubeの仕様変更により、一部の情報は取得が困難になっている点に注意
        response_data = VideoResponse(
            title=yt.title,
            channel_name=yt.author,
            video_url=video_url,
            # 日付を "YYYY-MM-DD" 形式の文字列に変換
            upload_date=yt.publish_date.strftime("%Y-%m-%d") if yt.publish_date else "N/A",
            view_count=yt.views,
            like_count=None,  # 現在のpytubeでは安定して取得できない
            subscriber_count=None, # pytubeでは取得不可
            transcript=transcript_text
        )
        logger.info(f"処理成功: {yt.title}")
        return response_data

    except NoTranscriptFound:
        # 文字起こしが見つからなかった場合の専用エラーハンドリング
        logger.warning(f"文字起こしが見つかりませんでした: {video_url}")
        raise HTTPException(status_code=404, detail="この動画には利用可能な文字起こしがありません。")
    
    except Exception as e:
        # その他の予期せぬエラーが発生した場合のハンドリング
        logger.error(f"処理中に予期せぬエラーが発生しました: {video_url}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"内部サーバーエラーが発生しました: {str(e)}")
