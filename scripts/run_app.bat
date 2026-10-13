@echo off
cd /d "%~dp0\.."
if "%1"=="" (set PORT=8501) else (set PORT=%1)
streamlit run app.py --server.port %PORT%
