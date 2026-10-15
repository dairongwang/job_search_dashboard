@echo off
rem Start the main (operation) dashboard. Usage: scripts\run_app.bat [port]
cd /d "%~dp0\.."
if "%1"=="" (set PORT=8501) else (set PORT=%1)
if "%PYTHON%"=="" (set PY=python) else (set PY=%PYTHON%)
%PY% -c "import streamlit, pandas, bs4" 2>nul || %PY% -m pip install -r requirements.txt
%PY% -m jobsearch_sources setup-browser || echo warning: headless browser not available; web-form sites will not work until it is
%PY% -m streamlit run app.py --server.port %PORT%
