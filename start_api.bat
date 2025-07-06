@echo off
chcp 65001 > nul

rem =============================================
rem FastAPI + Tailscale Funnel 同時起動ランチャー
rem =============================================

rem バッチと同じフォルダへ移動
pushd "%~dp0"

rem ---- FastAPI サーバー ----
echo [FastAPI] 起動スクリプトを開始...
start "FastAPI Server" "%~dp0run_fastapi.bat"

rem サーバーが立ち上がるまで少し待つ
timeout /t 5 /nobreak > nul

rem ---- Tailscale Funnel ----
echo [Funnel] 起動スクリプトを開始...
start "Tailscale Funnel" "%~dp0run_funnel.bat"

popd

echo すべてのプロセスを起動しました。
exit /b
chcp 65001 > nul

rem ===== 設定（必要なら書き換え） ======================
set "PROJECT_DIR=%~dp0"                       rem バッチと同じフォルダ
set "TAILSCALE_EXE=%ProgramFiles%\Tailscale\tailscale.exe"
set "PORT=10000"
rem =======================================================

rem ===== FastAPI サーバー起動（別ウィンドウ） ==========
echo [FastAPI] 起動中...
start "FastAPI Server" cmd /k ^
    "pushd \"%PROJECT_DIR%\" ^& ^
     .\.venv\Scripts\activate.bat ^& ^
     uvicorn main:app --host 0.0.0.0 --port %PORT%"

rem サーバーが立ち上がるまで少し待つ
timeout /t 5 /nobreak > nul

rem ===== Tailscale Funnel 起動（別ウィンドウ） =========
echo [Funnel] 起動中...
start "Tailscale Funnel" cmd /k ^
    "\"%TAILSCALE_EXE%\" funnel %PORT%"

echo すべて起動しました。ウィンドウを閉じないでください。
exit /b
