@echo off
cd /d "%~dp0"
set VENV=%LOCALAPPDATA%\foodland_venv

if not exist "%VENV%\Scripts\python.exe" (
    echo  Setup not complete. Please run setup.bat first.
    echo.
    pause
    exit /b 1
)

echo Starting Foodland Wudinna Store Dashboard...
echo.
echo The dashboard will open in your browser at http://localhost:8506
echo To stop the dashboard, close this window.
echo.
"%VENV%\Scripts\python" -m streamlit run dashboard.py --server.port 8506 --server.headless true --server.address 0.0.0.0
echo.
echo  Press any key to close...
pause > nul
