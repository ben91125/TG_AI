@echo off
cd /d "%~dp0"

if not exist ".env" (
    echo Missing .env. Please create it from .env.example first.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Missing .venv. Please run install_deps.cmd first.
    pause
    exit /b 1
)

echo.
echo Export time range uses local time: Asia/Taipei UTC+8.
echo Accepted formats:
echo   YYYY-MM-DD
echo   YYYY-MM-DD HH:MM
echo   YYYY-MM-DD HH:MM:SS
echo Leave blank to export without that limit.
echo.
set /p EXPORT_START=Start time ^(blank = no start limit^):
set /p EXPORT_END=End time ^(blank = no end limit^):
echo.

.venv\Scripts\python.exe -m src.tg_monitor.export_xlsx --start "%EXPORT_START%" --end "%EXPORT_END%"
if errorlevel 1 (
    echo Export failed.
    pause
    exit /b %errorlevel%
)

echo.
echo Export completed. The xlsx file is under:
echo %~dp0outputs\reports
pause
