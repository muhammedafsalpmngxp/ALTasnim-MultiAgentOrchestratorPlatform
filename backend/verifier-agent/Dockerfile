# verifier-agent: its own LangGraph Agent Server deployment on port 8203.
# Build context is backend/ (docker-compose.yml does this):
#   docker build -f verifier-agent/Dockerfile -t altasnim/verifier-agent .
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

WORKDIR /app/verifier-agent
EXPOSE 8203
HEALTHCHECK --interval=10s --timeout=5s --retries=12 CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('VERIFIER_PORT', '8203') + '/ok', timeout=4)"
# Listens on VERIFIER_PORT (backend/.env), default 8203
CMD ["sh", "-c", "exec langgraph dev --host 0.0.0.0 --port ${VERIFIER_PORT:-8203} --no-browser --no-reload"]
