@echo off
REM ===================================================================
REM  Laptop B: Staging-DCO (Port 8001) + eigener Cloudflare-Tunnel
REM  dynamic-claude-b -> bot-staging.dynamic-dome.com
REM  Konfliktfrei neben Laptop A (dynamic-claude / bot.dynamic-dome.com).
REM ===================================================================
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tunnel-b-control.ps1" -Action on
pause
