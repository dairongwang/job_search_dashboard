@echo off
cd /d "%~dp0\.."
if "%1"=="" (set PORT=8502) else (set PORT=%1)
streamlit run config_dashboard.py --server.port %PORT%
