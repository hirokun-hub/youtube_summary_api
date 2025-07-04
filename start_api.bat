@echo off
ECHO YouTube Summary APIサーバーを起動しています...

REM プロジェクトのディレクトリに移動します
cd C:\Users\hirok\Documents\Windsurf\811【開発】\youtube_summary_api

REM 1. FastAPIサーバーを新しいウィンドウで起動します
ECHO FastAPIサーバーを起動中...
start "FastAPI Server" cmd /k ".\.venv\Scripts\activate.bat && uvicorn main:app --host 127.0.0.1 --port 10000"

REM サーバーが起動するまで少し待ちます (5秒)
timeout /t 5 /nobreak

REM 2. Tailscale Funnelを新しいウィンドウで起動します
ECHO Tailscale Funnelを起動中...
start "Tailscale Funnel" cmd /k "\"C:\Program Files\Tailscale\tailscale.exe\" funnel 10000"

ECHO 自動起動スクリプトの処理が完了しました。
