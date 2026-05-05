@echo off
cd /d "%~dp0"
set VENV=%LOCALAPPDATA%\foodland_venv

REM ── Foodland Wudinna — Import Sales CSV ─────────────────────────────────────
REM
REM Usage:
REM   Drag a CSV file onto this .bat file  — imports it automatically
REM   Double-click this .bat file          — prompts you to paste a path
REM ─────────────────────────────────────────────────────────────────────────────

IF "%~1"=="" (
    echo Foodland Wudinna - Import Sales CSV
    echo.
    set /p CSV_PATH="Paste the path to the CSV file to import: "
) ELSE (
    set CSV_PATH=%~1
)

"%VENV%\Scripts\python" import_sales.py "%CSV_PATH%"

echo.
echo.
echo  Press any key to close...
pause > nul
