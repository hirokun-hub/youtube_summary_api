@echo off
chcp 65001 > nul

rem =============================================
rem Tailscale Funnel 起動用スクリプト
rem =============================================

set "TAILSCALE_EXE=%ProgramFiles%\Tailscale\tailscale.exe"
set "PORT=10000"

"%TAILSCALE_EXE%" funnel %PORT%

exit /b
