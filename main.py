# 必要なライブラリをインポート
import logging
import os
from dotenv import load_dotenv
from pathlib import Path
from fastapi import FastAPI, HTTPException, Security, Depends
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, HttpUrl
import requests
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound
import secrets
from urllib.parse import urlparse, parse_qs, urlunparse
import urllib.error
from requests.exceptions import HTTPError as RequestsHTTPError

# --- 環境変数の読み込み ---
# .envファイル (main.py と同じディレクトリ) から環境変数を読み込む
dotenv_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=dotenv_path)

# ---　ログ設定　---
# ログレベルを設定 (INFO, DEBUG, WARNING, ERROR, CRITICAL)
# この変数を変更することで、ログの詳細度を簡単に切り替え可能
LOG_LEVEL = "DEBUG"
logging.basicConfig(level=LOG_LEVEL, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
# デバッグ用ログ: .env のパスと読み込んだ API_KEY の有無を出力
logger.debug(f".env path: {dotenv_path} exists={dotenv_path.exists()} , API_KEY in env = {os.getenv('API_KEY')}")

# ---　FastAPIアプリケーションのインスタンスを作成　---
# APIのドキュメントに表示される情報を設定
app = FastAPI(
    title="YouTube動画情報取得API",
    description="指定されたYouTube動画のメタデータと文字起こしを取得するAPIです。",
    version="1.0.0",
)

# --- APIキー認証の設定 ---
# 環境変数からAPIキーを取得
API_KEY = os.getenv("API_KEY")
API_KEY_NAME = "X-API-KEY" # リクエストヘッダーに含めるキーの名前
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

async def verify_api_key(x_api_key: str = Security(api_key_header)):
    """APIキーを検証する依存関係関数"""
    # サーバー側にAPI_KEYが設定されているか、かつ空文字列でないかを確認
    if not API_KEY:
        logger.error("環境変数 'API_KEY' が設定されていません。")
        raise HTTPException(status_code=500, detail="サーバー側でAPIキーが設定されていません。")

    # 定数時間で比較することで、タイミング攻撃への耐性を持たせる
    # x_api_keyが存在することも確認
    if x_api_key and secrets.compare_digest(x_api_key, API_KEY):
        return x_api_key

    logger.warning(f"無効な、または提供されていないAPIキーが使用されました: '{x_api_key}'")
    raise HTTPException(
        status_code=403,
        detail="Could not validate credentials",
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
def get_summary(request: VideoRequest, _: str = Depends(verify_api_key)):
    """
    YouTube動画のURLを受け取り、動画のメタデータと文字起こしを返します。

    - **request**: `VideoRequest`モデル。`url`キーにYouTubeのURLを含むJSON。
    - **return**: `VideoResponse`モデル。動画情報を含むJSON。
    """
    # 入力URLから動画IDのみを抜き出して正規化（不要なクエリ文字列を削除）
    try:
        parsed = urlparse(str(request.url))
        if parsed.netloc in ("youtu.be", "www.youtu.be"):
            video_id = parsed.path.lstrip("/")
        else:
            qs = parse_qs(parsed.query)
            video_id = qs.get("v", [None])[0]
        if not video_id:
            raise ValueError("動画IDを取得できませんでした。URLを確認してください。")
        # URL再構築
        video_url = urlunparse(("https", "www.youtube.com", f"/watch?v={video_id}", "", "", ""))
    except Exception as parse_err:
        logger.warning(f"URL解析に失敗しました: {request.url} : {parse_err}")
        raise HTTPException(status_code=400, detail="無効なYouTube URL 形式です。")

    logger.info(f"処理開始: URL = {video_url}")

    try:
        # --- 1. oEmbed APIを使って動画のメタデータを取得 ---
        logger.debug("oEmbed API によるメタデータ取得を開始...")
        oembed_url = f"https://www.youtube.com/oembed?url={video_url}&format=json"
        meta_resp = requests.get(oembed_url, timeout=10)
        meta_resp.raise_for_status()
        meta_json = meta_resp.json()
        video_title = meta_json.get("title", "(取得失敗)")
        channel_name = meta_json.get("author_name", "(取得失敗)")
        logger.debug(f"動画タイトル: {video_title}")

        # --- 2. youtube-transcript-apiを使って文字起こしを取得 ---
        logger.debug(f"youtube-transcript-apiによる文字起こし取得を開始... (Video ID: {video_id})")
        # 日本語、または英語の文字起こしを試みる
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['ja', 'en'])
        
        # 取得した文字起こしデータをタイムスタンプ付きで結合
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
                if isinstance(elem, dict):
                    start = elem.get("start", 0)
                    text = elem.get("text", "")
                else:
                    start = getattr(elem, "start", 0)
                    text = getattr(elem, "text", "")
                transcript_lines.append(f"[{format_timestamp(start)}] {text}")
            except Exception as e_item:
                logger.debug(f"文字起こし要素の解析に失敗: {e_item} | elem={elem}")
        transcript_text = "\n".join(transcript_lines)
        logger.debug(f"文字起こしの取得に成功。文字数: {len(transcript_text)}")

        # --- 3. レスポンスデータを組み立てる ---
        logger.debug("レスポンスデータの組み立てを開始...")
        # pytubeの仕様変更により、一部の情報は取得が困難になっている点に注意
        response_data = VideoResponse(
            title=video_title,
            channel_name=channel_name,
            video_url=video_url,
            # 公開日の取得は oEmbed API では提供されないため N/A とする
            upload_date="N/A",
            view_count=0,
            like_count=None,  # 現在のpytubeでは安定して取得できない
            subscriber_count=None, # pytubeでは取得不可
            transcript=transcript_text
        )
        logger.info(f"処理成功: {video_title}")
        return response_data

    except NoTranscriptFound:
        # 文字起こしが見つからなかった場合の専用エラーハンドリング
        logger.warning(f"文字起こしが見つかりませんでした: {video_url}")
        raise HTTPException(status_code=404, detail="この動画には利用可能な文字起こしがありません。")
    
    except (urllib.error.HTTPError, RequestsHTTPError) as http_err:
        # YouTube 側から 4xx / 5xx が返った場合
        logger.warning(f"YouTube / oEmbed API から HTTPError が返されました: {http_err}")
        status_code = getattr(http_err, 'code', None)
        if status_code is None and hasattr(http_err, 'response') and http_err.response is not None:
            status_code = http_err.response.status_code
        raise HTTPException(status_code=status_code or 400, detail=f"YouTube から {status_code or 400} エラーが返されました。動画が存在しない / 制限されている可能性があります。")

    except Exception as e:
        # その他の予期せぬエラーが発生した場合のハンドリング
        logger.error(f"処理中に予期せぬエラーが発生しました: {video_url}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"内部サーバーエラーが発生しました: {str(e)}")
