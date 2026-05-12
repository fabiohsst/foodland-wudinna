@echo off
cd /d "%~dp0"
echo ============================================================
echo  Foodland Wudinna — First-Time Setup
echo ============================================================
echo.

:: Check Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  ERROR: Python is not installed or not on PATH.
    echo.
    echo  1. Go to https://www.python.org/downloads/
    echo  2. Download Python 3.10 or newer
    echo  3. During install, tick "Add Python to PATH"
    echo  4. Re-run this script
    echo.
    pause
    exit /b 1
)
echo  Python found:
python --version
echo.

:: Virtual environment lives outside the OneDrive folder so it never syncs.
set VENV=%LOCALAPPDATA%\foodland_venv

if not exist "%VENV%\Scripts\python.exe" (
    echo  Creating virtual environment at %VENV% ...
    python -m venv "%VENV%"
    echo  Done.
    echo.
) else (
    echo  Virtual environment already exists at %VENV%
    echo.
)

:: Install / update packages
echo  Installing packages (this may take a few minutes the first time)...
"%VENV%\Scripts\python" -m pip install --upgrade pip --quiet
"%VENV%\Scripts\python" -m pip install -r requirements.txt --quiet
echo  Done.
echo.

:: Create directories that are gitignored but required at runtime
echo  Creating required data directories...
if not exist "03_model\order_sheet\"   mkdir "03_model\order_sheet"
if not exist "04_ordering\"            mkdir "04_ordering"
if not exist "05_waste\"               mkdir "05_waste"
if not exist "01_data\raw\archive\"    mkdir "01_data\raw\archive"
if not exist "pricing\invoices\"       mkdir "pricing\invoices"
if not exist "pricing\reviews\"        mkdir "pricing\reviews"
echo  Done.
echo.

:: Git remote — consultant sets this up during handover visit.
:: Run the following command once (replace with actual repo URL + token):
::
::   git remote set-url origin https://<TOKEN>@github.com/<user>/foodland-wudinna.git
::
:: Windows Credential Manager will remember the token after the first pull.

echo ============================================================
echo  Setup complete.
echo  You can now use the Launch *.bat files to start the app.
echo ============================================================
echo.
pause
