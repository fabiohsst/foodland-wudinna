@echo off
cd /d "%~dp0"
set VENV=%LOCALAPPDATA%\foodland_venv

if not exist "%VENV%\Scripts\python.exe" (
    echo  Setup not complete. Please run setup.bat first.
    echo.
    pause
    exit /b 1
)

echo Starting Fruit ^& Veg Waste Dashboard...
echo.

REM Kill any process currently holding port 8507
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8507 "') do (
    taskkill /F /PID %%a >nul 2>&1
)

echo The dashboard will open in your browser at http://localhost:8507
echo To stop the dashboard, close this window.
echo.
"%VENV%\Scripts\python" -m streamlit run waste_dashboard.py --server.port 8507 --server.headless true --server.address 0.0.0.0
echo.
echo  Press any key to close...
pause > nul
