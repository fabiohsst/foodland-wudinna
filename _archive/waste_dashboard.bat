@echo off
echo Starting Fruit & Veg Waste Dashboard...
echo Please wait while your browser opens.

:: Run the Streamlit app
python -m streamlit run waste_dashboard.py

:: Keep the command prompt open in case of errors
pause