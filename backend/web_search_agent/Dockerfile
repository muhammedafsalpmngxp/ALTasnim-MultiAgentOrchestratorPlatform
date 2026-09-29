# web-search-agent: its own LangGraph Agent Server on port 8201, with only this agent's dependencies.
# Build context is backend/ (the shared utils/ package lives there):
#
#   cd backend/web_search_agent && docker compose up --build            # this agent only (docker-compose.yml here)
#   cd backend && docker compose up --build web-search-agent            # or as part of the platform
#   docker build -f web_search_agent/Dockerfile -t altasnim/web-search-agent .   # from backend/
#
# Build args:
#   TORCH_INDEX_URL   CPU-only torch by default (~200 MB instead of ~2.5 GB with CUDA);
#                     e.g. https://download.pytorch.org/whl/cu124 for an NVIDIA GPU (+ WEB_SEARCH_RERANKER_DEVICE=cuda)
#   PLAYWRIGHT=true   adds Chromium for JS-rendered pages (WEB_SEARCH_USE_PLAYWRIGHT_FALLBACK=true), ~500 MB more
#
# Runtime: `langgraph dev` (in-memory Agent Server, no license needed) for dev/test.
# Production: licensed Agent Server image (`langgraph build`) with Postgres + Redis.
FROM python:3.12-slim

ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
ARG PLAYWRIGHT=false

# PYTHONPATH: utils/ + this agent's package, in place, so models/ and logs/ stay relative to the agent folder.
# HF_HOME / PLAYWRIGHT_BROWSERS_PATH: caches in writable places (the app runs as a non-root user).
ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app:/app/web_search_agent/src \
    HF_HOME=/app/web_search_agent/models/.hf \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright

WORKDIR /app

# 1) third-party dependencies (cached layer): torch first so sentence-transformers does not pull the CUDA build;
#    web_search_agent/requirements.txt without the dev tools and the "-e .." line (the code is copied in step 2)
RUN pip install torch --index-url "${TORCH_INDEX_URL}"
COPY web_search_agent/requirements.txt /tmp/requirements.txt
RUN grep -vE '^\s*(-e |pytest|ruff)' /tmp/requirements.txt > /tmp/runtime.txt && pip install -r /tmp/runtime.txt
RUN if [ "${PLAYWRIGHT}" = "true" ]; then pip install "playwright>=1.45" && playwright install --with-deps chromium; fi

# 2) code: the shared utils/ package + this agent (tests, .env, models/, logs/ are left out by .dockerignore)
COPY utils/ utils/
COPY web_search_agent/ web_search_agent/

# models/ (reranker, downloaded on first use) and logs/ (saved runs for Retry) are volumes in docker-compose.yml
RUN useradd --create-home --uid 1000 app \
    && mkdir -p web_search_agent/models web_search_agent/logs \
    && chown -R app:app /app/web_search_agent
USER app

WORKDIR /app/web_search_agent
EXPOSE 8201
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=12 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8201/ok', timeout=4)"
CMD ["langgraph", "dev", "--host", "0.0.0.0", "--port", "8201", "--no-browser", "--no-reload"]
