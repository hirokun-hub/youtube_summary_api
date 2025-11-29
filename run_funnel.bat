@echo off
REM =============================================
REM 【非推奨】Docker Composeへの移行後は使用しない予定
REM 互換目的で残置しています
REM 推奨: docker compose up -d を使用してください
REM =============================================
chcp 65001 > nul

rem =============================================
rem Tailscale Funnel 起動用スクリプト
rem =============================================

set "TAILSCALE_EXE=%ProgramFiles%\Tailscale\tailscale.exe"
set "PORT=10000"

"%TAILSCALE_EXE%" funnel %PORT%

exit /b
