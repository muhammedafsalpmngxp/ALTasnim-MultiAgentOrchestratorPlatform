# Synthesizer agent: plain FastAPI app (no LangGraph).
#
# Build (from backend/Synthesizer-agent):
#   docker build -t altasnim/synthesizer-agent .
#
# Run (settings and the OpenAI key come from backend/.env, never baked into the image):
#   docker run --rm -p 8203:8203 --env-file ../.env -e SYNTHESIZER_RELOAD=false altasnim/synthesizer-agent
#
# The container listens on SYNTHESIZER_PORT (default 8204; docker-compose.yml uses 8204).

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 1) runtime dependencies only (the "# ---- tests" part of requirements.txt is left out); cached layer
COPY requirements.txt .
RUN sed '/^# ---- tests/,$d' requirements.txt > /tmp/requirements.txt \
    && pip install -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# 2) the agent (src/ holds the code and the prompt files)
COPY src ./src
COPY run.py .

# 3) run as a normal user, not root
RUN useradd --create-home --uid 10001 synthesizer
USER synthesizer

# Defaults; docker run -e / --env-file / docker-compose override them
ENV SYNTHESIZER_HOST=0.0.0.0 \
    SYNTHESIZER_PORT=8204 \
    SYNTHESIZER_RELOAD=false

EXPOSE 8204

HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=6 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('SYNTHESIZER_PORT', '8204') + '/ok', timeout=4)"

CMD ["python", "run.py"]
