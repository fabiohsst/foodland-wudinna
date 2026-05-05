@echo off
setlocal
cd /d "%~dp0"
set VENV=%LOCALAPPDATA%\foodland_venv

REM ── Launch Suggest PG Mappings ───────────────────────────────────────────────
REM Drag the weekly Freshlink price guide Excel onto this file.
REM Claude AI will suggest POS name matches for any unmatched descriptions.
REM Output: 01_data/reference/price_guide_mapping_staged.csv
REM
REM After reviewing the staged file, run:
REM   python suggest_pg_mappings.py --apply
REM ─────────────────────────────────────────────────────────────────────────────

if "%~1"=="" (
    echo.
    echo  Usage: Drag the Freshlink price guide Excel onto this file.
    echo.
    echo  After reviewing the staged CSV, apply it with:
    echo    python suggest_pg_mappings.py --apply
    echo.
    pause
    exit /b 1
)

echo.
echo  Generating mapping suggestions for: %~nx1
echo.

"%VENV%\Scripts\python" "%~dp0suggest_pg_mappings.py" "%~1"
set EXIT_CODE=%errorlevel%

echo.
if %EXIT_CODE%==0 (
    echo  Review 01_data/reference/price_guide_mapping_staged.csv
    echo  then run:  python suggest_pg_mappings.py --apply
) else (
    echo  Something went wrong ^(exit code %EXIT_CODE%^).
)
echo.
echo  Press any key to close...
pause > nul
