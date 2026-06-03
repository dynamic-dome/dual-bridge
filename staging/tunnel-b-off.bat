@echo off
REM ===================================================================
REM  Laptop B: Tunnel-B + Staging-DCO stoppen.
REM  Faehrt bot-staging.dynamic-dome.com herunter, Port 8001 frei.
REM ===================================================================
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tunnel-b-control.ps1" -Action off
pause
