@echo off
setlocal
cd /d "%~dp0"
"..\.venv\Scripts\python.exe" export.py %*
if errorlevel 1 pause

