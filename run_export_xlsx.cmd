@echo off
cd /d "%~dp0"

if not exist ".env" (
    echo Missing .env. Please create it from .env.example first.
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Missing .venv. Please run install_deps.cmd first.
    exit /b 1
)

.venv\Scripts\python.exe -m src.tg_monitor.export_xlsx

