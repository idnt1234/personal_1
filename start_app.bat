@echo off
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo Python not found: venv\Scripts\python.exe
    pause
    exit /b
)

if not exist "app_v2.py" (
    echo app_v2.py not found in current folder
    pause
    exit /b
)

start http://localhost:8501
"venv\Scripts\python.exe" -m streamlit run "app_v2.py" --server.address 0.0.0.0 --server.port 8501

pause