@echo off
cd /d "%~dp0"
set VENV=%LOCALAPPDATA%\foodland_venv

echo Stockout Detector ^— Foodland Wudinna
echo.
if "%~1"=="" (
    echo Usage: Drag and drop a SOH Excel file onto this bat file.
    echo.
    echo The script will:
    echo   1. Identify items with zero stock that were actively selling
    echo   2. Count lost trading days until the next delivery
    echo   3. Estimate lost revenue per item
    echo   4. Append results to 05_waste\Stockout_Log.csv
    echo      ^(Re-running on the same SOH file safely overwrites those rows^)
    echo.
    pause
    exit /b
)
echo Processing: %~1
echo.
"%VENV%\Scripts\python" detect_stockouts.py "%~1"
echo.
echo  Press any key to close...
pause > nul
