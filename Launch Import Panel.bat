@echo off
cd /d "%~dp0"
set VENV=%LOCALAPPDATA%\foodland_venv

if not exist "%VENV%\Scripts\python.exe" (
    echo  Setup not complete. Please run setup.bat first.
    echo.
    pause
    exit /b 1
)

echo Starting Import Panel...
echo.
echo The panel will open in your browser at http://localhost:8509
echo To stop, close this window.
echo.
"%VENV%\Scripts\python" -m streamlit run import_panel.py --server.port 8509 --server.headless true --server.address 0.0.0.0
echo.
echo Press any key to close...
pause > nul
