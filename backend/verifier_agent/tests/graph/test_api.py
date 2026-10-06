"""The custom routes: the card, the verdict list for verifier-ui. Nothing else can start a check (no /verify)."""

from fastapi.testclient import TestClient
from verifier_agent.api import app

from verifier_agent import calls

client = TestClient(app)


def test_card():
    body = client.get("/card").json()
    assert body["name"] == "verifier" and body["role"] == "verifier"


def test_calls_list_and_clear():
    calls.CALLS.clear()
    calls.CALLS.appendleft({"id": "1", "question": "q", "result": {"passed": True}})
    assert client.get("/verify/calls").json()[0]["id"] == "1"
    assert client.delete("/verify/calls").json() == {"cleared": True}
    assert client.get("/verify/calls").json() == []


def test_status_shows_the_model(monkeypatch):
    monkeypatch.setenv("VERIFIER_LLM_MODEL", "gpt-4o-mini")
    assert client.get("/verify/status").json() == {"model": "openai:gpt-4o-mini", "mode": "llm"}
    monkeypatch.delenv("VERIFIER_LLM_MODEL")
    assert client.get("/verify/status").json()["mode"] == "rules only"


def test_the_old_push_route_is_gone():
    assert client.post("/verify", json={"summary": "x"}).status_code in (404, 405)
