FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/models

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# Keep the tokenizer and torch thread pools small and predictable (stability of native code under threads)
ENV TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=4 MKL_NUM_THREADS=4

# The LangGraph Agent Server (langgraph dev): its own layer, so the large model layer above stays cached
RUN pip install "langgraph>=1.2,<2" "langgraph-cli[inmem]>=0.4,<1"

COPY langgraph.json .
COPY rag_agent ./rag_agent
ENV PYTHONPATH=/app

EXPOSE 8000
# The models load at startup (~30 s from the cache, longer on the very first run while they download)
HEALTHCHECK --interval=15s --timeout=5s --start-period=120s --retries=5 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('RAG_PORT', '8000') + '/health', timeout=4)"
# Listens on RAG_PORT (backend/.env), default 8000: the graph "rag" (for the supervisor) + the HTTP routes (rag-ui)
CMD ["sh", "-c", "exec langgraph dev --host 0.0.0.0 --port ${RAG_PORT:-8000} --no-browser --no-reload"]
