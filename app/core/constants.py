"""アプリケーション全体で使用する定数を一元管理する。"""

# --- エラーコード ---
ERROR_INVALID_URL = "INVALID_URL"
ERROR_VIDEO_NOT_FOUND = "VIDEO_NOT_FOUND"
ERROR_TRANSCRIPT_NOT_FOUND = "TRANSCRIPT_NOT_FOUND"
ERROR_TRANSCRIPT_DISABLED = "TRANSCRIPT_DISABLED"
ERROR_RATE_LIMITED = "RATE_LIMITED"
ERROR_METADATA_FAILED = "METADATA_FAILED"
ERROR_INTERNAL = "INTERNAL_ERROR"

# --- 字幕取得の言語優先順位 ---
TRANSCRIPT_LANGUAGES = ['ja', 'en']

# --- oEmbed API ---
OEMBED_URL_TEMPLATE = "https://www.youtube.com/oembed?url={url}&format=json"
OEMBED_TIMEOUT_SECONDS = 10

# --- yt-dlp キー名 → レスポンスフィールド名のマッピング ---
YTDLP_KEY_MAP = {
    "channel": "channel_name",
    "thumbnail": "thumbnail_url",
}

# yt-dlp の extract_info から取得するキーの一覧（マッピング不要のもの）
YTDLP_DIRECT_KEYS = [
    "title", "upload_date", "duration", "duration_string",
    "view_count", "like_count", "description", "tags",
    "categories", "channel_id", "channel_follower_count", "webpage_url",
]

# --- メッセージ ---
MSG_SUCCESS = "Successfully retrieved data."
MSG_INVALID_URL = "無効なYouTube動画URLです。有効なURL形式か確認してください。"
MSG_VIDEO_NOT_FOUND = "YouTubeから情報を取得できませんでした。動画が存在しないか、非公開の可能性があります。"
MSG_TRANSCRIPT_NOT_FOUND = "この動画には利用可能な文字起こしがありませんでした。"
MSG_TRANSCRIPT_DISABLED = "この動画では字幕機能が無効化されています。"
MSG_RATE_LIMITED = "YouTubeへのリクエストが多すぎるため、一時的に情報を取得できません。時間をおいて再度お試しください。"
MSG_INTERNAL_ERROR = "内部処理中に予期せぬエラーが発生しました。"
MSG_METADATA_FAILED = "メタデータの取得に失敗しましたが、字幕は正常に取得できました。"

# --- エラーコード → メッセージのマッピング ---
ERROR_CODE_TO_MESSAGE = {
    ERROR_INVALID_URL: MSG_INVALID_URL,
    ERROR_VIDEO_NOT_FOUND: MSG_VIDEO_NOT_FOUND,
    ERROR_TRANSCRIPT_NOT_FOUND: MSG_TRANSCRIPT_NOT_FOUND,
    ERROR_TRANSCRIPT_DISABLED: MSG_TRANSCRIPT_DISABLED,
    ERROR_RATE_LIMITED: MSG_RATE_LIMITED,
    ERROR_METADATA_FAILED: MSG_METADATA_FAILED,
    ERROR_INTERNAL: MSG_INTERNAL_ERROR,
}
