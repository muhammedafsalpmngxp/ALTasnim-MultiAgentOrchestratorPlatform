"""Settings from environment variables (see .env.example)."""

import os
from dataclasses import dataclass


def parse_endpoints(value: str) -> tuple[tuple[int, str], ...]:
    """'8203/synthesize, 8210/answer' -> ((8203, '/synthesize'), (8210, '/answer'))."""
    endpoints = []
    for entry in (e.strip() for e in value.split(",")):
        if not entry:
            continue
        port, _, path = entry.partition("/")
        if not port.strip().isdigit():
            raise ValueError(f"NEXT_AGENTS entry {entry!r} must look like PORT/PATH, e.g. 8203/synthesize")
        endpoints.append((int(port), "/" + path.strip()))
    return tuple(endpoints)


@dataclass(frozen=True)
class Settings:
    qdrant_url: str = os.getenv("QDRANT_URL", "http://localhost:6333")
    qdrant_collection: str = os.getenv("QDRANT_COLLECTION", "rag_chunks")
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
    rerank_model: str = os.getenv("RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
    chunk_words: int = int(os.getenv("CHUNK_WORDS", "300"))
    chunk_overlap_words: int = int(os.getenv("CHUNK_OVERLAP_WORDS", "50"))
    candidates: int = int(os.getenv("CANDIDATES", "20"))  # per search leg, and sent to the reranker
    top_k: int = int(os.getenv("TOP_K", "5"))  # chunks returned by /retrieve (default)
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "50"))
    # Next agents: /retrieve POSTs {question, chunks} to every PORT/PATH in NEXT_AGENTS. The machine for
    # each one is found automatically on the LAN (see discovery.py). Empty = don't pass on.
    next_agents: tuple[tuple[int, str], ...] = parse_endpoints(os.getenv("NEXT_AGENTS", ""))
    next_agent_subnet: str = os.getenv("NEXT_AGENT_SUBNET", "")  # network to search, e.g. 192.168.1.0/24
    next_agent_timeout: float = float(os.getenv("NEXT_AGENT_TIMEOUT", "120"))


settings = Settings()
