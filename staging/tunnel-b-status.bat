@echo off
REM ===================================================================
REM  Laptop B: Status von Staging-DCO, Tunnel-B und beiden Webhooks.
REM ===================================================================
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tunnel-b-control.ps1" -Action status
pause
