@echo off
cd /d "%~dp0"
set VENV=%LOCALAPPDATA%\foodland_venv

echo ============================================================
echo  Foodland Wudinna — Update
echo ============================================================
echo.

:: Pull latest code from GitHub
echo  Pulling latest code...
git pull
if %errorlevel% neq 0 (
    echo.
    echo  ERROR: Git pull failed.
    echo  Check your internet connection, or contact your consultant.
    echo.
    pause
    exit /b 1
)
echo.

:: Reinstall packages only if requirements.txt changed
echo  Checking packages...
"%VENV%\Scripts\pip" install -r requirements.txt --quiet
echo  Done.
echo.

echo  Update complete. Restart any open apps for changes to take effect.
echo.
pause
