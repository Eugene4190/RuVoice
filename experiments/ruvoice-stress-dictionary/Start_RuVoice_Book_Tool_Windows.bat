@echo off
setlocal
cd /d "%~dp0"
python private_book_server.py
if errorlevel 1 (
  echo.
  echo RuVoice book tool could not start. Install Python 3.11+ and retry.
  pause
)
