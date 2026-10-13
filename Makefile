.PHONY: install install-config dev app config test lint validate init-config docker-up docker-config

PY ?= python

install:            ## main app dependencies
	$(PY) -m pip install -r requirements.txt

install-config:     ## configuration dashboard only
	$(PY) -m pip install -r requirements-config.txt

dev:                ## everything incl. tests
	$(PY) -m pip install -r requirements-dev.txt

browser:            ## optional headless Chromium for JavaScript-rendered job boards
	$(PY) -m pip install -r requirements-browser.txt
	$(PY) -m playwright install chromium

app:                ## run the main dashboard on :8501
	streamlit run app.py --server.port 8501

config:             ## run the configuration dashboard on :8502
	streamlit run config_dashboard.py --server.port 8502

init-config:        ## write a default config file (no-op if it exists)
	$(PY) -m jobsearch_config init || true

validate:           ## validate the active configuration (exit 2 on errors)
	$(PY) -m jobsearch_config validate

test:
	$(PY) -m pytest -q

lint:
	$(PY) -m pyflakes app.py config_dashboard.py jobsearch_config jobsearch_sources tests

docker-up:          ## operation only
	docker compose up --build app

docker-config:      ## operation + configuration dashboard
	docker compose --profile config up --build
