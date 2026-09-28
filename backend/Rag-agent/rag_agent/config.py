"""Settings from environment variables (see .env.example)."""

import os
from dataclasses import dataclass


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


settings = Settings()
