@echo off
rem One-time setup: Python packages for both dashboards + the headless Chromium used for web-form sites (idempotent).
cd /d "%~dp0\.."
if "%PYTHON%"=="" (set PY=python) else (set PY=%PYTHON%)
%PY% -m pip install --upgrade pip >nul
%PY% -m pip install -r requirements.txt -r requirements-config.txt || exit /b 1
%PY% -m jobsearch_sources setup-browser || exit /b 1
echo Setup complete. Start with scripts\run_app.bat and scripts\run_config.bat
