"""Shared fixtures: an in-memory Qdrant (real query logic, no server) and a stand-in for bge-m3."""

import zlib

import pytest
from qdrant_client import QdrantClient
from rag_agent import store
from rag_agent.models import Embedding


def _token(word: str) -> int:
    return zlib.crc32(word.encode()) % 50_000


def _fake_embed(texts: list[str]) -> list[Embedding]:
    """Deterministic stand-in for bge-m3: sparse = word counts, dense = normalized hashed bag of words."""
    out = []
    for text in texts:
        sparse: dict[int, float] = {}
        dense = [0.0] * 8
        for word in text.lower().split():
            sparse[_token(word)] = sparse.get(_token(word), 0.0) + 1.0
            dense[_token(word) % 8] += 1.0
        norm = sum(x * x for x in dense) ** 0.5
        out.append(Embedding([x / norm for x in dense], sparse))
    return out


@pytest.fixture
def fake_embed():
    return _fake_embed


@pytest.fixture
def qdrant(monkeypatch):
    client = QdrantClient(":memory:")
    monkeypatch.setattr(store, "client", lambda: client)
    return client
