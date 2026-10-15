@echo off
rem Start the configuration dashboard. Usage: scripts\run_config.bat [port]
cd /d "%~dp0\.."
if "%1"=="" (set PORT=8502) else (set PORT=%1)
if "%PYTHON%"=="" (set PY=python) else (set PY=%PYTHON%)
%PY% -c "import streamlit, bs4" 2>nul || %PY% -m pip install -r requirements-config.txt
%PY% -m jobsearch_sources setup-browser || echo warning: headless browser not available; 'Find jobs' tests of web-form sites will not work until it is
%PY% -m streamlit run config_dashboard.py --server.port %PORT%
