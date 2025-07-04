# app/core/logging_config.py

"""
このモジュールは、アプリケーション全体のロギング設定を管理します。
"""

import logging
import os

def setup_logging():
    """
    アプリケーションのロギングをセットアップします。
    ログレベルは環境変数 'LOG_LEVEL' から取得し、デフォルトは 'INFO' です。
    """
    # 環境変数からログレベルを取得。指定がなければ 'INFO' を使用。
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    
    # 文字列のログレベルを logging の定数に変換
    numeric_level = getattr(logging, log_level, logging.INFO)
    
    # 基本的なロギング設定
    # フォーマット: [タイムスタンプ] [ログレベル] [ロガー名] メッセージ
    logging.basicConfig(
        level=numeric_level,
        format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # Uvicornのアクセスログが重複しないように設定
    logging.getLogger("uvicorn.access").propagate = False

    # 設定完了をログに出力
    logger = logging.getLogger(__name__)
    logger.info(f"ロギングを設定しました。ログレベル: {log_level}")
