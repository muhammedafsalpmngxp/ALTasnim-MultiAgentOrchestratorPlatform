"""API flow: real store on an in-memory Qdrant, stand-ins for the models (no download)."""

import dataclasses

import httpx
import pytest
from fastapi.testclient import TestClient
from qdrant_client import QdrantClient
from rag_agent import discovery, main, models, store

SYNTH = (8203, "/synthesize")


@pytest.fixture
def api(qdrant, fake_embed, monkeypatch):
    monkeypatch.setattr(models, "embed", fake_embed)
    # relevance = share of question words found in the passage
    monkeypatch.setattr(models, "rerank", lambda q, ps: [
        len(set(q.lower().split()) & set(p.lower().split())) / len(q.split()) for p in ps])
    monkeypatch.setattr(main, "settings", dataclasses.replace(main.settings, next_agents=()))
    return TestClient(main.app)


@pytest.fixture
def next_agents(monkeypatch):
    """Fake next agents. `hosts[(port, path)]` = what each LAN scan finds for that endpoint (in order);
    `reply(request)` = how the agents answer."""
    sent, scans = [], []
    state = {"hosts": {SYNTH: ["http://192.168.1.33:8203"]},
             "reply": lambda request: httpx.Response(200, json={"answer": "Retention is five percent."})}

    def discover(port, path):
        scans.append((port, path))
        found = state["hosts"].get((port, path), [])
        return found.pop(0) if found else None

    def post(url, json, timeout):
        request = httpx.Request("POST", url, json=json)
        sent.append({"url": url, "json": json, "timeout": timeout})
        response = state["reply"](request)
        response.request = request
        return response

    def configure(*endpoints):
        replaced = dataclasses.replace(main.settings, next_agents=endpoints, next_agent_timeout=30)
        monkeypatch.setattr(main, "settings", replaced)
        monkeypatch.setattr(discovery, "settings", replaced)

    configure(SYNTH)
    monkeypatch.setattr(discovery, "_found", {})
    monkeypatch.setattr(discovery, "discover", discover)
    monkeypatch.setattr(main.httpx, "post", post)
    return sent, scans, state, configure


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
    assert api.post("/retrieve", json={"question": "anything"}).json() == {
        "question": "anything", "chunks": [], "next_agents": []}


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
    unreachable = QdrantClient(url="http://127.0.0.1:1", timeout=2, check_compatibility=False)
    monkeypatch.setattr(store, "client", lambda: unreachable)
    r = api.get("/documents")
    assert r.status_code == 503 and "Qdrant unavailable" in r.json()["detail"]


def test_health(api):
    assert api.get("/health").json() == {"status": "ok"}


# ---- passing {question, chunks} to the next agents ---------------------------------------------------


def test_question_and_chunks_go_to_the_discovered_agent(api, next_agents):
    sent, _, _, _ = next_agents
    upload(api, "notes.txt", b"retention money is five percent")

    body = api.post("/retrieve", json={"question": "retention money"}).json()

    [call] = sent
    assert call["url"] == "http://192.168.1.33:8203/synthesize" and call["timeout"] == 30
    assert call["json"] == {"question": "retention money", "chunks": body["chunks"]}
    assert body["chunks"][0]["content"] == "retention money is five percent"
    assert body["next_agents"] == [{"endpoint": "8203/synthesize", "url": "http://192.168.1.33:8203/synthesize",
                                    "status": 200, "response": {"answer": "Retention is five percent."}}]


def test_multiple_endpoints_each_get_the_chunks(api, next_agents):
    sent, scans, state, configure = next_agents
    configure(SYNTH, (8210, "/answer"))
    state["hosts"][(8210, "/answer")] = ["http://192.168.1.40:8210"]

    body = api.post("/retrieve", json={"question": "q"}).json()

    assert sorted(c["url"] for c in sent) == ["http://192.168.1.33:8203/synthesize", "http://192.168.1.40:8210/answer"]
    assert sorted(scans) == [SYNTH, (8210, "/answer")]
    assert [r["endpoint"] for r in body["next_agents"]] == ["8203/synthesize", "8210/answer"]  # config order
    assert all(r["status"] == 200 for r in body["next_agents"])


def test_one_failing_endpoint_does_not_affect_the_others(api, next_agents):
    _, _, state, configure = next_agents
    configure(SYNTH, (8210, "/answer"))  # nothing serves 8210/answer

    body = api.post("/retrieve", json={"question": "q"}).json()
    ok, missing = body["next_agents"]
    assert ok["status"] == 200
    assert missing == {"endpoint": "8210/answer", "url": None,
                       "error": "No machine in the local network has port 8210 open and serves /answer"}


def test_found_machine_is_remembered(api, next_agents):
    _, scans, _, _ = next_agents
    api.post("/retrieve", json={"question": "one"})
    api.post("/retrieve", json={"question": "two"})
    assert scans == [SYNTH]


def test_no_machine_found_still_returns_the_chunks(api, next_agents):
    _, _, state, _ = next_agents
    state["hosts"] = {}
    upload(api, "notes.txt", b"retention money is five percent")

    body = api.post("/retrieve", json={"question": "retention money"}).json()
    assert len(body["chunks"]) == 1
    error = body["next_agents"][0]["error"]
    assert error == "No machine in the local network has port 8203 open and serves /synthesize"


def test_machine_gone_is_found_again(api, next_agents):
    sent, scans, state, _ = next_agents
    state["hosts"] = {SYNTH: ["http://192.168.1.33:8203", "http://192.168.1.40:8203"]}

    def reply(request):
        if request.url.host == "192.168.1.33":  # old machine no longer answers
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(200, json={"answer": "ok"})

    state["reply"] = reply
    [result] = api.post("/retrieve", json={"question": "q"}).json()["next_agents"]
    assert [c["url"] for c in sent] == ["http://192.168.1.33:8203/synthesize", "http://192.168.1.40:8203/synthesize"]
    assert scans == [SYNTH, SYNTH]
    assert result["url"] == "http://192.168.1.40:8203/synthesize" and result["response"] == {"answer": "ok"}


def test_machine_gone_and_none_found(api, next_agents):
    _, _, state, _ = next_agents

    def refuse(request):
        raise httpx.ConnectError("connection refused", request=request)

    state["reply"] = refuse
    [result] = api.post("/retrieve", json={"question": "q"}).json()["next_agents"]
    assert result == {"endpoint": "8203/synthesize", "url": "http://192.168.1.33:8203/synthesize",
                      "error": "connection refused"}


def test_http_error_keeps_the_chunks(api, next_agents):
    _, _, state, _ = next_agents
    state["reply"] = lambda request: httpx.Response(500, text="boom")
    upload(api, "notes.txt", b"retention money is five percent")

    r = api.post("/retrieve", json={"question": "retention money"})
    assert r.status_code == 200 and len(r.json()["chunks"]) == 1
    assert "500" in r.json()["next_agents"][0]["error"]


def test_plain_text_reply(api, next_agents):
    _, _, state, _ = next_agents
    state["reply"] = lambda request: httpx.Response(200, text="plain answer")
    assert api.post("/retrieve", json={"question": "q"}).json()["next_agents"][0]["response"] == "plain answer"
