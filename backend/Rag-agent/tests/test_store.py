"""Qdrant store against an in-memory Qdrant."""

import pytest
from rag_agent import store
from rag_agent.config import settings


@pytest.fixture
def add(qdrant, fake_embed):
    def _add(document_id: str, name: str, texts: list[str], page: int | None = None) -> None:
        store.add_chunks(document_id, name, [(page, t) for t in texts], fake_embed(texts))
    return _add


def test_collection_has_dense_and_sparse_vectors(qdrant, add):
    add("d1", "a.pdf", ["retention is five percent", "steel price per ton"])
    params = qdrant.get_collection(settings.qdrant_collection).config.params
    assert params.vectors["dense"].size == 8
    assert "sparse" in params.sparse_vectors
    assert qdrant.count(settings.qdrant_collection).count == 2


def test_hybrid_search_finds_the_matching_chunk_first(add, fake_embed):
    add("d1", "a.txt", ["weather is sunny today", "retention money is five percent", "steel price per ton"])
    results = store.hybrid_search(fake_embed(["retention money"])[0], n=3)
    assert results[0]["content"] == "retention money is five percent"
    assert set(results[0]) == {"id", "document_id", "document_name", "chunk_index", "page", "content"}
    assert len(results) == 3


def test_hybrid_search_respects_n(add, fake_embed):
    add("d1", "a.txt", [f"chunk number {i}" for i in range(10)])
    assert len(store.hybrid_search(fake_embed(["chunk number 3"])[0], n=4)) == 4


def test_empty_store(qdrant, fake_embed):
    assert store.hybrid_search(fake_embed(["anything"])[0], n=5) == []
    assert store.list_documents() == []
    assert store.get_chunks("d1") == []
    assert store.delete_document("d1") == 0


def test_list_get_and_delete(add):
    add("d1", "a.pdf", ["one two", "three four"], page=1)
    add("d2", "b.txt", ["five six"])

    assert sorted(store.list_documents(), key=lambda d: d["document_id"]) == [
        {"document_id": "d1", "document_name": "a.pdf", "chunks": 2},
        {"document_id": "d2", "document_name": "b.txt", "chunks": 1},
    ]
    chunks = store.get_chunks("d1")
    assert [(c["chunk_index"], c["page"], c["content"]) for c in chunks] == [(0, 1, "one two"), (1, 1, "three four")]

    assert store.delete_document("d1") == 2
    assert store.get_chunks("d1") == []
    assert [d["document_id"] for d in store.list_documents()] == ["d2"]
