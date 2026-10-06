@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo ERROR: Python was not found on PATH.
    echo Install Python 3.10+ from https://python.org and make sure "Add python.exe to PATH" is checked during setup.
    echo See README.md -^> Troubleshooting -^> "Python not found" for details.
    exit /b 1
)

if not exist "backend\.venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv backend\.venv
    if errorlevel 1 (
        echo ERROR: failed to create the virtual environment. See README.md -^> Troubleshooting.
        exit /b 1
    )
)

echo Installing pinned dependencies...
backend\.venv\Scripts\pip.exe install -q -r backend\requirements.txt
if errorlevel 1 (
    echo ERROR: pip install failed. See README.md -^> Troubleshooting -^> "pip blocked".
    exit /b 1
)

echo.
backend\.venv\Scripts\python.exe backend\scripts\startup_check.py > "%TEMP%\reo_startup_check.txt"
type "%TEMP%\reo_startup_check.txt"

set "PORT=8000"
for /f "tokens=2 delims==" %%p in ('findstr /b "PORT=" "%TEMP%\reo_startup_check.txt"') do set "PORT=%%p"
del "%TEMP%\reo_startup_check.txt" >nul 2>nul

echo.
echo Starting the server on http://localhost:%PORT% ...
cd backend
start /B "" .venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port %PORT%
cd ..

timeout /t 2 /nobreak >nul
start "" "http://localhost:%PORT%"

echo.
echo Server running in the background on port %PORT% (browser opened automatically).
echo To stop it: close this window, or find and end the "uvicorn" / python.exe process in Task Manager.
