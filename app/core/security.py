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
