"""Settings from environment variables: the RAG_* keys of the shared backend/.env (see backend/.env.example)."""

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
            raise ValueError(f"RAG_NEXT_AGENTS entry {entry!r} must look like PORT/PATH, e.g. 8203/synthesize")
        endpoints.append((int(port), "/" + path.strip()))
    return tuple(endpoints)


@dataclass(frozen=True)
class Settings:
    qdrant_url: str = os.getenv("RAG_QDRANT_URL", "http://localhost:6333")
    qdrant_collection: str = os.getenv("RAG_QDRANT_COLLECTION", "rag_chunks")
    embedding_model: str = os.getenv("RAG_EMBEDDING_MODEL", "BAAI/bge-m3")
    rerank_model: str = os.getenv("RAG_RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
    chunk_words: int = int(os.getenv("RAG_CHUNK_WORDS", "300"))
    chunk_overlap_words: int = int(os.getenv("RAG_CHUNK_OVERLAP_WORDS", "50"))
    candidates: int = int(os.getenv("RAG_CANDIDATES", "20"))  # per search leg, and sent to the reranker
    top_k: int = int(os.getenv("RAG_TOP_K", "5"))  # chunks returned by /retrieve (default)
    max_upload_mb: int = int(os.getenv("RAG_MAX_UPLOAD_MB", "50"))
    # Next agents: /retrieve POSTs {question, chunks} to every PORT/PATH in RAG_NEXT_AGENTS. The machine for
    # each one is found automatically on the LAN (see discovery.py). Empty = don't pass on.
    next_agents: tuple[tuple[int, str], ...] = parse_endpoints(os.getenv("RAG_NEXT_AGENTS", ""))
    next_agent_subnet: str = os.getenv("RAG_NEXT_AGENT_SUBNET", "")  # network to search, e.g. 192.168.1.0/24
    next_agent_timeout: float = float(os.getenv("RAG_NEXT_AGENT_TIMEOUT", "120"))


settings = Settings()
