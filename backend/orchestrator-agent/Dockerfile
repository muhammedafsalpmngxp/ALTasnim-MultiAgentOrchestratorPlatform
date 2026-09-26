# orchestrator-agent: its own LangGraph Agent Server deployment on port 8100.
# Build context is backend/ (docker-compose.yml does this):
#   docker build -f orchestrator-agent/Dockerfile -t altasnim/orchestrator-agent .
#
# Runtime: `langgraph dev` (in-memory Agent Server, no license needed) for dev/test.
# Production: licensed Agent Server image (`langgraph build`) with Postgres + Redis.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 1) third-party dependencies from backend/requirements.txt (cached layer; "-e ." is installed in step 2)
COPY requirements.txt .
RUN grep -v '^-e ' requirements.txt > /tmp/requirements.txt && pip install -r /tmp/requirements.txt

# 2) project code (backend/pyproject.toml packages utils + all agents)
COPY . .
RUN pip install --no-deps -e .

WORKDIR /app/orchestrator-agent
EXPOSE 8100
HEALTHCHECK --interval=10s --timeout=5s --retries=12 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8100/ok', timeout=4)"
CMD ["langgraph", "dev", "--host", "0.0.0.0", "--port", "8100", "--no-browser", "--no-reload"]
