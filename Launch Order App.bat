@echo off
cd /d "%~dp0"
set VENV=%LOCALAPPDATA%\foodland_venv

if not exist "%VENV%\Scripts\python.exe" (
    echo  Setup not complete. Please run setup.bat first.
    echo.
    pause
    exit /b 1
)

echo Starting Fruit ^& Veg Order Sheet Generator...
echo.
echo The app will open in your browser at http://localhost:8501
echo To stop the app, close this window.
echo.
"%VENV%\Scripts\python" -m streamlit run app.py --server.headless true --server.address 0.0.0.0
echo.
echo  Press any key to close...
pause > nul
