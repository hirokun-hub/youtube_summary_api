@echo off
chcp 65001 > nul

rem =============================================
rem FastAPI サーバー単体起動用スクリプト
rem 別ウィンドウで呼び出されることを想定
rem =============================================

rem バッチと同じフォルダへ移動（日本語パス対応）
pushd "%~dp0"

rem 仮想環境をアクティベート（call で戻れるように）
call .\.venv\Scripts\activate.bat

rem Uvicorn を起動（停止は Ctrl+C）
uvicorn main:app --host 0.0.0.0 --port 10000

popd
exit /b
