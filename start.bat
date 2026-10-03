@echo off
echo ============================================
echo  Renewable Energy Orchestrator - Starting
echo ============================================
echo.

start "Backend (Gemini API) - port 8000" cmd /k ""%~dp0backend\run_server.bat""
echo Started backend window. Waiting for it to boot...
timeout /t 4 /nobreak >nul

start "Frontend (Dashboard) - port 5173" cmd /k ""%~dp0frontend\run_dev.bat""
echo Started frontend window. Waiting for it to boot...
timeout /t 5 /nobreak >nul

start http://localhost:5173

echo.
echo Done. Two new windows opened (Backend and Frontend) - keep BOTH open while you use the app.
echo Your dashboard should now be open in your browser at http://localhost:5173
echo.
echo To stop the app: just close the Backend and Frontend windows.
echo.
pause
