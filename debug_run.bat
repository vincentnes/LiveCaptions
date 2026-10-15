@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Live Captions (debug) / 即時字幕（除錯模式）
echo Debug mode: errors will be shown in this window.
echo 除錯模式：程式出問題時，這個黑色視窗會顯示錯誤訊息。
echo Log file / 紀錄檔: %APPDATA%\LiveCaptions\log.txt
echo.
"venv\Scripts\python.exe" app.py
pause
