@echo off
cd /d "%~dp0"
echo Starting Fruit ^& Veg Order Sheet Generator...
echo.
echo The app will open in your browser at http://localhost:8501
echo To stop the app, close this window.
echo.
python -m streamlit run app.py --server.headless false
pause
