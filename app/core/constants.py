"""アプリケーション全体で使用する定数を一元管理する。"""

# --- エラーコード ---
ERROR_INVALID_URL = "INVALID_URL"
ERROR_VIDEO_NOT_FOUND = "VIDEO_NOT_FOUND"
ERROR_TRANSCRIPT_NOT_FOUND = "TRANSCRIPT_NOT_FOUND"
ERROR_TRANSCRIPT_DISABLED = "TRANSCRIPT_DISABLED"
ERROR_RATE_LIMITED = "RATE_LIMITED"
ERROR_CLIENT_RATE_LIMITED = "CLIENT_RATE_LIMITED"
ERROR_METADATA_FAILED = "METADATA_FAILED"
ERROR_INTERNAL = "INTERNAL_ERROR"
# /search 用追加エラーコード
ERROR_QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
ERROR_UNAUTHORIZED = "UNAUTHORIZED"

# --- クライアント側レート制限 ---
# 同じAPIインスタンスへのリクエスト最低間隔(秒)。
# YouTubeへの集中アクセスでブロックされるのを予防的に防ぐ。
CLIENT_RATE_LIMIT_INTERVAL_SECONDS = 60

# --- 字幕取得の言語優先順位 ---
TRANSCRIPT_LANGUAGES = ['ja', 'en']

# --- oEmbed API ---
OEMBED_URL_TEMPLATE = "https://www.youtube.com/oembed?url={url}&format=json"
OEMBED_TIMEOUT_SECONDS = 10

# --- YouTube Data API v3 ---
YOUTUBE_API_V3_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
YOUTUBE_API_V3_CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"
YOUTUBE_API_V3_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_API_V3_VIDEOS_PART = "snippet,contentDetails,statistics"
# channel_created_at（snippet.publishedAt）を取得するため snippet を含める
YOUTUBE_API_V3_CHANNELS_PART = "snippet,statistics"
YOUTUBE_API_V3_SEARCH_PART = "snippet"
YOUTUBE_API_V3_SEARCH_TYPE = "video"
YOUTUBE_API_V3_SEARCH_MAX_RESULTS = 50
YOUTUBE_API_V3_VIDEOS_BATCH_SIZE = 50
YOUTUBE_API_V3_CHANNELS_BATCH_SIZE = 50
YOUTUBE_API_V3_TIMEOUT = (3.05, 10)
YOUTUBE_API_V3_MAX_RETRIES = 3
YOUTUBE_API_V3_RETRY_STATUS_CODES = {500, 502, 503, 504}
YOUTUBE_API_V3_RETRY_BASE_DELAY = 1
YOUTUBE_WATCH_URL_TEMPLATE = "https://www.youtube.com/watch?v={video_id}"
YOUTUBE_THUMBNAIL_PRIORITY = ["maxres", "standard", "high", "medium", "default"]

# --- YouTubeカテゴリ ---
YOUTUBE_CATEGORY_MAP = {
    "1": "Film & Animation",
    "2": "Autos & Vehicles",
    "10": "Music",
    "15": "Pets & Animals",
    "17": "Sports",
    "18": "Short Movies",
    "19": "Travel & Events",
    "20": "Gaming",
    "21": "Videoblogging",
    "22": "People & Blogs",
    "23": "Comedy",
    "24": "Entertainment",
    "25": "News & Politics",
    "26": "Howto & Style",
    "27": "Education",
    "28": "Science & Technology",
    "29": "Nonprofits & Activism",
    "30": "Movies",
    "31": "Anime/Animation",
    "32": "Action/Adventure",
    "33": "Classics",
    "34": "Comedy",
    "35": "Documentary",
    "36": "Drama",
    "37": "Family",
    "38": "Foreign",
    "39": "Horror",
    "40": "Sci-Fi/Fantasy",
    "41": "Thriller",
    "42": "Shorts",
    "43": "Shows",
    "44": "Trailers",
}

# --- メッセージ ---
MSG_SUCCESS = "Successfully retrieved data."
MSG_INVALID_URL = "無効なYouTube動画URLです。有効なURL形式か確認してください。"
MSG_VIDEO_NOT_FOUND = "YouTubeから情報を取得できませんでした。動画が存在しないか、非公開の可能性があります。"
MSG_TRANSCRIPT_NOT_FOUND = "この動画には利用可能な文字起こしがありませんでした。"
MSG_TRANSCRIPT_DISABLED = "この動画では字幕機能が無効化されています。"
MSG_RATE_LIMITED = "YouTubeへのリクエストが多すぎるため、一時的に情報を取得できません。時間をおいて再度お試しください。"
MSG_CLIENT_RATE_LIMITED = "リクエスト間隔が短すぎます。{retry_after}秒後に再試行してください。"
MSG_QUOTA_EXCEEDED = "YouTube APIの日次クォータを超過しました。太平洋時間の午前0時（日本時間の午後5時頃）にリセットされます。"
MSG_INTERNAL_ERROR = "内部処理中に予期せぬエラーが発生しました。"
MSG_METADATA_FAILED = "メタデータの取得に失敗しましたが、字幕は正常に取得できました。"

# --- /search 用メッセージ ---
# /search は AI エージェント / LLM Tool 消費前提のため、レスポンスの message 本文は
# 英語固定（既存 /summary の日本語メッセージは iPhone ショートカット後方互換のため維持）。
MSG_UNAUTHORIZED = "Invalid or missing X-API-KEY header."
MSG_QUOTA_EXCEEDED_TEMPLATE = (
    "YouTube Data API daily quota ({daily_limit} units) exhausted. "
    "Resets in {reset_in_seconds} seconds (at {reset_jst} JST)."
)
MSG_SEARCH_CLIENT_RATE_LIMITED_TEMPLATE = (
    "Search rate limit exceeded: more than {max_req} requests in the last {window} seconds. "
    "Rule: max {max_req} requests per {window} seconds. Retry after {retry_after} seconds."
)

# --- /search 用クライアントレート制限 ---
SEARCH_RATE_LIMIT_WINDOW_SECONDS = 60
SEARCH_RATE_LIMIT_MAX_REQUESTS = 10

# --- YouTube Data API v3 クォータ ---
YOUTUBE_DAILY_QUOTA_LIMIT = 10_000
YOUTUBE_QUOTA_TIMEZONE = "America/Los_Angeles"
QUOTA_COST_SEARCH_LIST = 100
QUOTA_COST_VIDEOS_LIST = 1
QUOTA_COST_CHANNELS_LIST = 1

# --- SQLite ---
USAGE_DB_PATH = "data/usage/usage.db"
SQLITE_BUSY_TIMEOUT_MS = 5000

# --- エラーコード → メッセージのマッピング ---
# 注: ERROR_CLIENT_RATE_LIMITED は MSG_CLIENT_RATE_LIMITED がテンプレート文字列のため
# このマップには含めない（router 層で .format() 経由で組み立てる）
ERROR_CODE_TO_MESSAGE = {
    ERROR_INVALID_URL: MSG_INVALID_URL,
    ERROR_VIDEO_NOT_FOUND: MSG_VIDEO_NOT_FOUND,
    ERROR_TRANSCRIPT_NOT_FOUND: MSG_TRANSCRIPT_NOT_FOUND,
    ERROR_TRANSCRIPT_DISABLED: MSG_TRANSCRIPT_DISABLED,
    ERROR_RATE_LIMITED: MSG_RATE_LIMITED,
    ERROR_METADATA_FAILED: MSG_METADATA_FAILED,
    ERROR_INTERNAL: MSG_INTERNAL_ERROR,
}
