FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/models

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# Keep the tokenizer and torch thread pools small and predictable (stability of native code under threads)
ENV TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=4 MKL_NUM_THREADS=4

COPY rag_agent ./rag_agent

EXPOSE 8000
# The models load at startup (~30 s from the cache, longer on the very first run while they download)
HEALTHCHECK --interval=15s --timeout=5s --start-period=120s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"
CMD ["uvicorn", "rag_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
