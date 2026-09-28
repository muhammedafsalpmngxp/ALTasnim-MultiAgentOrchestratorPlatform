"""Hybrid search logic against a fake Elasticsearch client (no server needed)."""

import pytest
from rag_agent import store
from rag_agent.config import settings


def hit(hit_id: str, content: str = "") -> dict:
    return {"_id": hit_id, "_source": {"document_id": "d", "content": content or hit_id}}


class FakeIndices:
    def __init__(self, exists: bool):
        self._exists = exists
        self.created = None

    def exists(self, index):
        return self._exists

    def create(self, index, mappings):
        self.created = mappings
        self._exists = True


class FakeES:
    def __init__(self, bm25=(), dense=(), exists=True):
        self.indices = FakeIndices(exists)
        self.bm25, self.dense = list(bm25), list(dense)
        self.calls = []

    def search(self, **kwargs):
        self.calls.append(kwargs)
        return {"hits": {"hits": self.dense if "knn" in kwargs else self.bm25}}


@pytest.fixture
def fake(monkeypatch):
    def install(es):
        monkeypatch.setattr(store, "client", lambda: es)
        return es
    return install


def test_rrf_prefers_hits_found_by_both_legs():
    fused = store._rrf([[hit("a"), hit("b"), hit("c")], [hit("c"), hit("d")]], n=10)
    assert [c["id"] for c in fused] == ["c", "a", "b", "d"]  # b and d tie; order kept
    assert fused[0] == {"id": "c", "document_id": "d", "content": "c"}


def test_rrf_keeps_top_n():
    assert [c["id"] for c in store._rrf([[hit("a"), hit("b"), hit("c")]], n=2)] == ["a", "b"]


def test_hybrid_search_sends_bm25_and_knn_queries(fake):
    es = fake(FakeES(bm25=[hit("a"), hit("b")], dense=[hit("b"), hit("c")]))
    fused = store.hybrid_search("retention percent", [0.1, 0.2], n=5)

    bm25, dense = es.calls
    assert bm25["query"] == {"match": {"content": "retention percent"}} and bm25["size"] == 5
    assert dense["knn"] == {"field": "embedding", "query_vector": [0.1, 0.2], "k": 5, "num_candidates": 100}
    assert [c["id"] for c in fused] == ["b", "a", "c"]


def test_hybrid_search_without_index_is_empty(fake):
    es = fake(FakeES(exists=False))
    assert store.hybrid_search("q", [0.1], n=5) == []
    assert es.calls == []


def test_add_chunks_creates_index_and_bulk_indexes(fake, monkeypatch):
    es = fake(FakeES(exists=False))
    sent = {}

    def bulk(client, actions, refresh):
        sent.update(client=client, actions=list(actions), refresh=refresh)

    monkeypatch.setattr(store.helpers, "bulk", bulk)
    store.add_chunks("doc1", "a.pdf", [(1, "first"), (2, "second")], [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])

    assert es.indices.created["properties"]["embedding"] == {
        "type": "dense_vector", "dims": 3, "index": True, "similarity": "cosine"}
    assert es.indices.created["properties"]["content"] == {"type": "text"}
    assert sent["refresh"] == "wait_for" and sent["client"] is es
    assert [a["_id"] for a in sent["actions"]] == ["doc1_0", "doc1_1"]
    assert sent["actions"][1]["_index"] == settings.es_index
    assert sent["actions"][1]["_source"] == {"document_id": "doc1", "document_name": "a.pdf", "chunk_index": 1,
                                             "page": 2, "content": "second", "embedding": [0.4, 0.5, 0.6]}
