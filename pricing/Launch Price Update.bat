@echo off
REM Launch Price Update — Foodland Wudinna
REM Drag and drop a Freshlink invoice PDF (or CSV) onto this file.
REM A price review Excel will be saved to pricing\reviews\

cd /d "%~dp0.."
set VENV=%LOCALAPPDATA%\foodland_venv

"%VENV%\Scripts\python" pricing\generate_price_updates.py --invoice "%~1"
pause
