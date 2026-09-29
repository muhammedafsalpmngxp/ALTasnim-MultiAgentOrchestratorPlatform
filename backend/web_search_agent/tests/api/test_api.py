"""Custom routes (langgraph.json -> http.app): /card for the orchestrator, /custom/* for web-search-ui."""

import json

import pytest
from fastapi.testclient import TestClient
from web_search_agent.api import app


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def search(client, **body) -> list[tuple[str, dict]]:
    with client.stream("POST", "/custom/search/stream", json=body) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        return parse_sse("".join(r.iter_text()))


def test_card_for_the_orchestrator_registry(client):
    card = client.get("/card").json()
    assert card["name"] == "web_search" and card["approval_mode"] == "none"


def test_search_stream_sends_steps_then_result(fake_web, client):
    events = search(client, query="solid-state batteries", trace_id="ui-1", include_domains=["example.com"])

    assert events[0][0] == "steps" and len(events[0][1]["steps"]) == 6
    assert events[-1][0] == "result"
    result = events[-1][1]  # the full run details (the orchestrator only gets question + top 3)
    assert result["trace_id"] == "ui-1" and result["status"] == "ok" and result["evidence"]
    assert len(result["findings"]) <= 3
    assert fake_web["search_calls"][0]["include_domains"] == ["example.com"]  # form fields -> task params
    verify = next(s for s in result["steps"] if s["id"] == "verify")
    assert verify["status"] == "skipped"  # UI runs have no verifier step


def test_history_and_sources_after_a_run(fake_web, client):
    search(client, query="solid-state batteries", trace_id="ui-2")

    runs = client.get("/custom/history").json()
    assert runs[0]["trace_id"] == "ui-2" and runs[0]["sources"] >= 1
    assert runs[0]["source_agent"] == "web-search-ui"

    sources = client.get("/custom/sources", params={"trace_id": "ui-2"}).json()
    assert sources["question"] == "solid-state batteries" and sources["findings"] and sources["citations"]
    assert client.get("/custom/sources", params={"trace_id": "missing"}).status_code == 404


def test_validation_providers_and_health(client):
    assert client.post("/custom/search/stream", json={"query": ""}).status_code == 422
    assert client.get("/custom/sources").json() == {"providers": [{"name": "sample", "configured": True}],
                                                    "offline": True}
    health = client.get("/custom/health").json()
    assert health["status"] == "ok" and health["agent"] == "web_search" and health["offline"] is True
    assert health["llm"]["configured"] is False
