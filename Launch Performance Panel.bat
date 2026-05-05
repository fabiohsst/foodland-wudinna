@echo off
cd /d "%~dp0"
set VENV=%LOCALAPPDATA%\foodland_venv

if not exist "%VENV%\Scripts\python.exe" (
    echo  Setup not complete. Please run setup.bat first.
    echo.
    pause
    exit /b 1
)

echo Starting Fruit ^& Veg Performance Panel...
echo.
echo The panel will open in your browser at http://localhost:8505
echo To stop the panel, close this window.
echo.
"%VENV%\Scripts\python" -m streamlit run panel.py --server.port 8505 --server.headless true --server.address 0.0.0.0
echo.
echo  Press any key to close...
pause > nul
