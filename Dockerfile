# One image, two entrypoints. The compose file (or your orchestrator) decides
# which dashboard a container runs, so operation and configuration can be
# deployed, scaled and secured independently.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    JOB_SEARCH_CONFIG=/data/job_search_config.json \
    JOB_SEARCH_DB=/data/job_search.db

# Playwright + Chromium (JavaScript-rendered boards, sites searched through their own form) are included by default;
# build with --build-arg WITH_BROWSER=0 for a smaller image without them.
ARG WITH_BROWSER=1

WORKDIR /app
COPY requirements.txt requirements-config.txt requirements-browser.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-config.txt \
    && if [ "$WITH_BROWSER" = "1" ]; then \
         pip install --no-cache-dir -r requirements-browser.txt \
         && python -m playwright install --with-deps chromium; \
       fi

COPY jobsearch_config ./jobsearch_config
COPY jobsearch_sources ./jobsearch_sources
COPY app.py config_dashboard.py ./
COPY config/job_search_config.example.json ./config/

RUN mkdir -p /data && useradd --create-home appuser && chown -R appuser /app /data \
    && if [ -d /root/.cache/ms-playwright ]; then mkdir -p /home/appuser/.cache && mv /root/.cache/ms-playwright /home/appuser/.cache/ && chown -R appuser /home/appuser/.cache; fi
USER appuser
VOLUME ["/data"]

# Default: the main dashboard. Override the command for the configuration dashboard.
EXPOSE 8501 8502
CMD ["streamlit", "run", "app.py", "--server.port", "8501", "--server.address", "0.0.0.0"]
