@echo off
cd /d "%~dp0"

python3.12.exe -m venv .venv
if errorlevel 1 exit /b %errorlevel%

call .venv\Scripts\activate.bat
python -m pip install -r requirements.txt

