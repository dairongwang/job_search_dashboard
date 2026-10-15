.PHONY: install install-config dev app config test lint validate init-config docker-up docker-config

PY ?= python

install:            ## main app dependencies (+ headless Chromium)
	$(PY) -m pip install -r requirements.txt
	$(PY) -m jobsearch_sources setup-browser

install-config:     ## configuration dashboard only (+ headless Chromium for 'Find jobs' tests)
	$(PY) -m pip install -r requirements-config.txt
	$(PY) -m jobsearch_sources setup-browser

dev:                ## everything incl. tests
	$(PY) -m pip install -r requirements-dev.txt
	$(PY) -m jobsearch_sources setup-browser

browser:            ## (re)install the headless Chromium used for JavaScript boards and web-form sites
	$(PY) -m jobsearch_sources setup-browser

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
