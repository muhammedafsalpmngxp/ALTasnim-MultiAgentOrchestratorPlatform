"""API flow: real store on an in-memory Qdrant, stand-ins for the models (no download)."""

import dataclasses

import pytest
from fastapi.testclient import TestClient
from qdrant_client import QdrantClient
from rag_agent import main, models, store


@pytest.fixture
def api(qdrant, fake_embed, monkeypatch):
    monkeypatch.setattr(models, "embed", fake_embed)
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


def test_qdrant_down_is_503(api, monkeypatch):
    unreachable = QdrantClient(url="http://127.0.0.1:1", timeout=2)
    monkeypatch.setattr(store, "client", lambda: unreachable)
    r = api.get("/documents")
    assert r.status_code == 503 and "Qdrant unavailable" in r.json()["detail"]


def test_health(api):
    assert api.get("/health").json() == {"status": "ok"}
