@echo off
setlocal
cd /d "%~dp0"
set VENV=%LOCALAPPDATA%\foodland_venv

REM ── Launch Parse Price Guide ─────────────────────────────────────────────────
REM Drag the weekly Freshlink price guide Excel onto this file to parse it.
REM Output: 01_data/operational/supplier_prices_YYYYMMDD.csv
REM ─────────────────────────────────────────────────────────────────────────────

if "%~1"=="" (
    echo.
    echo  Usage: Drag the Freshlink price guide Excel onto this file.
    echo.
    pause
    exit /b 1
)

echo.
echo  Parsing price guide: %~nx1
echo.

"%VENV%\Scripts\python" "%~dp0parse_price_guide.py" "%~1"

echo.
if %errorlevel%==0 (
    echo  Done. Check 01_data/operational/ for the supplier_prices file.
) else (
    echo  An error occurred — see message above.
)
echo.
echo  Press any key to close...
pause > nul
