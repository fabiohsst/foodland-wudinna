@echo off
cd /d "%~dp0"
set VENV=%LOCALAPPDATA%\foodland_venv

if not exist "%VENV%\Scripts\python.exe" (
    echo  Setup not complete. Please run setup.bat first.
    echo.
    pause
    exit /b 1
)

echo Starting Fruit ^& Veg Price Update Panel...
echo.
echo The panel will open in your browser at http://localhost:8508
echo To stop the panel, close this window.
echo.
"%VENV%\Scripts\python" -m streamlit run pricing_panel.py --server.port 8508 --server.headless true --server.address 0.0.0.0
echo.
echo  Press any key to close...
pause > nul
