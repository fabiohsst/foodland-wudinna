@echo off
cd /d "%~dp0"

echo Foodland Wudinna — Order App (Docker)
echo.

docker compose up --build -d
if %errorlevel% neq 0 (
    echo.
    echo  ERROR: Docker is not running or not installed.
    echo  Download Docker Desktop from https://www.docker.com/products/docker-desktop
    echo.
    pause
    exit /b 1
)

echo.
echo  App is running at http://localhost:8501
echo  Opening browser...
echo.
timeout /t 3 /nobreak > nul
start http://localhost:8501

echo  To stop the app, run:  docker compose down
echo.
pause > nul
