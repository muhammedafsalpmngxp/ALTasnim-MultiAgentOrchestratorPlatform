"""bge-m3 dense embeddings and bge-reranker scores. Models load on first use (downloaded from
Hugging Face the first time) and run on the GPU with fp16 when CUDA is available."""

import threading

from .config import settings

_lock = threading.Lock()
_embedder = None
_reranker = None


def _cuda() -> bool:
    import torch

    return torch.cuda.is_available()


def _get_embedder():
    global _embedder
    with _lock:
        if _embedder is None:
            from FlagEmbedding import BGEM3FlagModel

            _embedder = BGEM3FlagModel(settings.embedding_model, use_fp16=_cuda())
    return _embedder


def _get_reranker():
    global _reranker
    with _lock:
        if _reranker is None:
            from FlagEmbedding import FlagReranker

            _reranker = FlagReranker(settings.rerank_model, use_fp16=_cuda(), normalize=True)
    return _reranker


def embed(texts: list[str]) -> list[list[float]]:
    """Normalized dense vectors, one per text."""
    return _get_embedder().encode(texts, batch_size=16, max_length=1024)["dense_vecs"].tolist()


def rerank(question: str, passages: list[str]) -> list[float]:
    """Relevance of each passage to the question, 0..1."""
    return [float(s) for s in _get_reranker().compute_score([(question, p) for p in passages])]
