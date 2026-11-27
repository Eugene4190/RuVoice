@echo off
setlocal
cd /d "%~dp0"

if exist "%~dp0RuVoiceBookTool.exe" (
    echo Starting RuVoice book tool...
    echo The private page will open in your browser.
    echo Keep this window open while using the tool. Press Ctrl+C to stop it.
    "%~dp0RuVoiceBookTool.exe"
    goto :end
)

where py >nul 2>nul
if %errorlevel%==0 (
    py -3.11 private_book_server.py
    goto :end
)

where python >nul 2>nul
if %errorlevel%==0 (
    python private_book_server.py
    goto :end
)

echo.
echo RuVoice Book Tool is not installed.
echo Download the Windows portable ZIP from the GitHub Actions run linked in the project README.
echo No separate Python installation is needed for the portable ZIP.
pause
exit /b 1

:end
if errorlevel 1 (
    echo.
    echo RuVoice Book Tool stopped with an error.
    pause
)
