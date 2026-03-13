@echo off
title AZIM AI TRADER v3 - STREAMLIT
color 0B
echo =========================================
echo    AZIM AI TRADER v3 - STREAMLIT UI
echo =========================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found! Please install Python 3.9+
    pause
    exit /b 1
)

REM Install requirements
echo [1/3] Checking dependencies...
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo ERROR: Failed to install dependencies!
    pause
    exit /b 1
)

echo [2/3] Starting Streamlit App...
echo.
echo Dashboard will open in your browser automatically.
echo If not, go to: http://localhost:8501
echo.
echo =========================================

streamlit run streamlit_app.py

pause
