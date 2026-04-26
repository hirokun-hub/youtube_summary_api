# app/core/security.py

"""
このモジュールは、APIの認証とセキュリティに関連する機能を提供します。
APIキーの検証ロジックなどをここに集約します。
"""

import os
import secrets
import logging

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from app.core.constants import ERROR_UNAUTHORIZED, MSG_UNAUTHORIZED

# このモジュール用のロガーを設定
logger = logging.getLogger(__name__)

# --- 環境変数と定数の設定 ---

# .envファイルからAPIキーを読み込む
API_KEY = os.getenv("API_KEY")
if not API_KEY:
    # API_KEYが設定されていない場合は、警告ログを出力し、アプリケーションの起動を妨げないようにする
    # ただし、この状態ではAPIは正常に機能しない
    logger.error("環境変数 'API_KEY' が設定されていません。API認証は機能しません。")

API_KEY_NAME = "X-API-KEY"

# FastAPIのセキュリティスキーマを定義
# これにより、Swagger UI上でAPIキーを入力するフィールドが自動的に生成される
API_KEY_HEADER = APIKeyHeader(name=API_KEY_NAME, auto_error=False)


# --- 依存関係関数 ---

async def verify_api_key(api_key_header: str = Security(API_KEY_HEADER)):
    """
    APIキーを検証するためのFastAPIの依存関係（Depends）関数。
    リクエストヘッダーに含まれるAPIキーが、環境変数で設定されたキーと一致するかを検証します。

    Args:
        api_key_header: リクエストヘッダーから抽出されたAPIキー。

    Raises:
        HTTPException: APIキーが存在しない、または無効な場合に403エラーを発生させます。

    Returns:
        str: 検証が成功した場合、提供されたAPIキーを返します。
    """
    if not API_KEY:
        # 環境変数が設定されていない場合、サーバー内部の問題として500エラーを返す
        logger.critical("APIキーがサーバーに設定されていないため、リクエストを処理できません。")
        raise HTTPException(
            status_code=500, 
            detail="サーバー側の設定エラーです。管理者に連絡してください。"
        )

    if not api_key_header:
        logger.warning("APIキーがリクエストヘッダーに含まれていません。")
        raise HTTPException(
            status_code=403,
            detail="API key is missing",
        )

    # secrets.compare_digest を使って、タイミング攻撃に対して安全な比較を行う
    if secrets.compare_digest(api_key_header, API_KEY):
        # キーが一致した場合、キーを返す（将来的な利用のため）
        return api_key_header
    else:
        # キーが一致しなかった場合
        logger.warning("無効なAPIキーが提供されました。")
        raise HTTPException(
            status_code=403,
            detail="Could not validate credentials",
        )


class SearchHTTPException(HTTPException):
    """`/search` 専用の HTTPException サブクラス。

    `detail` に dict を含み、レスポンスボディとしてその内容を **そのまま JSON 本体**
    として返すために独立した型として宣言する。**専用ハンドラ** (main.py の
    `search_http_exception_handler`) で処理することで、グローバル `HTTPException`
    ハンドラの挙動を上書きする副作用が他エンドポイントに波及するのを防ぐ
    （既存 `/summary` の `HTTPException(detail=str)` は FastAPI 標準ハンドラで
    `{"detail": "..."}` 形式に整形され続ける）。
    """


async def verify_api_key_for_search(
    api_key_header: str = Security(API_KEY_HEADER),
) -> str:
    """`/search` 専用の認証依存。

    既存 `verify_api_key`（403 を投げる）と並走させる。`/search` は AI エージェント /
    LLM Tool 消費前提のため、認証エラー時は LLM Tool SDK の自動リトライ分岐に
    沿った **HTTP 401** を返す（`/summary` の 403 互換は `verify_api_key` 側で維持）。

    `SearchHTTPException(detail=dict)` を投げ、main.py の専用ハンドラで `detail`
    を JSON 本体としてそのまま返すことで FR-4 / FR-5 の 401 レスポンス契約を満たす
    （quota は含めない）。グローバル `HTTPException` ハンドラには干渉しない。
    """
    if not API_KEY:
        logger.critical(
            "APIキーがサーバーに設定されていないため、/search リクエストを処理できません。"
        )
        raise HTTPException(
            status_code=500,
            detail="サーバー側の設定エラーです。管理者に連絡してください。",
        )

    if not api_key_header or not secrets.compare_digest(api_key_header, API_KEY):
        logger.warning("/search に無効または欠落した X-API-KEY が提供されました。")
        raise SearchHTTPException(
            status_code=401,
            detail={
                "success": False,
                "status": "error",
                "error_code": ERROR_UNAUTHORIZED,
                "message": MSG_UNAUTHORIZED,
                "query": None,
                "results": None,
            },
        )
    return api_key_header
