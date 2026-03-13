@echo off
title AZIM AI TRADER v3
color 0A
echo =========================================
echo    AZIM AI TRADER v3 - Starting...
echo =========================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python nahi mila! Python 3.9+ install karein
    pause
    exit /b 1
)

REM Install requirements
echo [1/3] Dependencies install ho rahi hain...
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo ERROR: Dependencies install nahi huin!
    pause
    exit /b 1
)

echo [2/3] Bot start ho raha hai...
echo.
echo Dashboard: http://localhost:8000
echo Discord notifications: ON
echo.
echo [3/3] Logs:
echo =========================================

python app.py

pause
