"""API flow with fake models and an in-memory store (no Elasticsearch, no model download)."""

import dataclasses

import pytest
from elasticsearch import ConnectionError as ESConnectionError
from fastapi.testclient import TestClient
from rag_agent import main, models, store


@pytest.fixture
def api(monkeypatch):
    chunks: dict[str, dict] = {}

    def add_chunks(document_id, document_name, doc_chunks, vectors):
        assert len(doc_chunks) == len(vectors)
        for i, (page, text) in enumerate(doc_chunks):
            chunks[f"{document_id}_{i}"] = {"id": f"{document_id}_{i}", "document_id": document_id,
                                            "document_name": document_name, "chunk_index": i, "page": page,
                                            "content": text}

    def delete_document(document_id):
        ids = [k for k, c in chunks.items() if c["document_id"] == document_id]
        for k in ids:
            del chunks[k]
        return len(ids)

    def list_documents():
        docs: dict[str, dict] = {}
        for c in chunks.values():
            d = docs.setdefault(c["document_id"], {"document_id": c["document_id"],
                                                   "document_name": c["document_name"], "chunks": 0})
            d["chunks"] += 1
        return list(docs.values())

    monkeypatch.setattr(store, "add_chunks", add_chunks)
    monkeypatch.setattr(store, "hybrid_search", lambda q, v, n: [dict(c) for c in list(chunks.values())[:n]])
    monkeypatch.setattr(store, "get_chunks", lambda d: [c for c in chunks.values() if c["document_id"] == d])
    monkeypatch.setattr(store, "delete_document", delete_document)
    monkeypatch.setattr(store, "list_documents", list_documents)
    monkeypatch.setattr(models, "embed", lambda texts: [[0.5, 0.5] for _ in texts])
    # relevance = share of question words found in the passage
    monkeypatch.setattr(models, "rerank", lambda q, ps: [
        len(set(q.lower().split()) & set(p.lower().split())) / len(q.split()) for p in ps])
    return TestClient(main.app)


def upload(api, name: str, content: bytes):
    return api.post("/documents", files={"file": (name, content)})


def test_upload_list_and_inspect(api):
    r = upload(api, "notes.txt", b"retention is five percent\nsteel price is high")
    assert r.status_code == 201
    doc = r.json()
    assert doc["document_name"] == "notes.txt" and doc["chunks"] == 1

    assert api.get("/documents").json() == [{"document_id": doc["document_id"], "document_name": "notes.txt",
                                             "chunks": 1}]
    [chunk] = api.get(f"/documents/{doc['document_id']}/chunks").json()
    assert chunk["content"] == "retention is five percent\nsteel price is high" and chunk["page"] is None


def test_retrieve_returns_reranked_chunks(api, monkeypatch):
    monkeypatch.setattr(main, "settings", dataclasses.replace(main.settings, chunk_words=5, chunk_overlap_words=0))
    upload(api, "spec.md", b"weather is sunny today\nretention money is five percent\nsteel price per ton")

    r = api.post("/retrieve", json={"question": "what is the retention money", "top_k": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["question"] == "what is the retention money"
    assert [c["content"] for c in body["chunks"]] == ["retention money is five percent", "weather is sunny today"]
    assert body["chunks"][0]["score"] == 0.6  # 3 of the 5 question words
    assert set(body["chunks"][0]) == {"id", "document_id", "document_name", "chunk_index", "page", "content", "score"}


def test_retrieve_with_no_documents(api):
    assert api.post("/retrieve", json={"question": "anything"}).json() == {"question": "anything", "chunks": []}


def test_retrieve_validates_input(api):
    assert api.post("/retrieve", json={"question": ""}).status_code == 422
    assert api.post("/retrieve", json={"question": "q", "top_k": 0}).status_code == 422


def test_upload_errors(api, monkeypatch):
    assert upload(api, "drawing.dwg", b"x").status_code == 400
    assert upload(api, "empty.txt", b"   \n  ").status_code == 422
    monkeypatch.setattr(main, "settings", dataclasses.replace(main.settings, max_upload_mb=0))
    assert upload(api, "big.txt", b"some text").status_code == 413


def test_delete(api):
    doc = upload(api, "a.txt", b"hello world").json()
    assert api.delete(f"/documents/{doc['document_id']}").status_code == 204
    assert api.delete(f"/documents/{doc['document_id']}").status_code == 404
    assert api.get(f"/documents/{doc['document_id']}/chunks").status_code == 404


def test_elasticsearch_down_is_503(api, monkeypatch):
    def down():
        raise ESConnectionError("connection refused")

    monkeypatch.setattr(store, "list_documents", down)
    r = api.get("/documents")
    assert r.status_code == 503 and "Elasticsearch unavailable" in r.json()["detail"]


def test_health(api):
    assert api.get("/health").json() == {"status": "ok"}
