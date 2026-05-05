@echo off
cd /d "%~dp0"
set VENV=%LOCALAPPDATA%\foodland_venv

if not exist "%VENV%\Scripts\python.exe" (
    echo  Setup not complete. Please run setup.bat first.
    echo.
    pause
    exit /b 1
)

"%VENV%\Scripts\python" -m jupyter --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  Installing Jupyter...
    "%VENV%\Scripts\pip" install jupyter --quiet
    echo  Done.
    echo.
)

echo Starting Jupyter Notebook...
echo.
echo Jupyter will open in your browser.
echo To stop, press Ctrl+C in this window.
echo.
"%VENV%\Scripts\jupyter" notebook
echo.
pause > nul
