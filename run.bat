@echo off
rem iPhone Photo Export - Windows launcher.
rem Double-click this file. First run creates a virtual environment and installs
rem the dependencies; later runs just start the app.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    py -3 -m venv .venv 2>nul || python -m venv .venv
    if not exist ".venv\Scripts\python.exe" (
        echo.
        echo Python was not found. Install Python 3.11 or newer from python.org
        echo and tick "Add python.exe to PATH" during setup.
        pause
        exit /b 1
    )
    echo Installing dependencies ^(one time, needs internet^)...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo Dependency install failed. Check your internet connection and retry.
        pause
        exit /b 1
    )
)

echo Starting iPhone Photo Export...
".venv\Scripts\python.exe" app.py
if errorlevel 1 pause
