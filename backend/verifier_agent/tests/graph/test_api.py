"""POST /verify: pushed output is verified, then {question, verification, inputs} goes to the synthesizer."""

import httpx
from fastapi.testclient import TestClient
from verifier_agent import api

RAG_OUTPUT = {"question": "What is the notice period?",
              "chunks": [{"document_name": "contract.pdf", "content": "The notice period is 30 days."}]}


def _mock_synthesizer(monkeypatch, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(api.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))


def test_verdict_is_sent_to_the_synthesizer(monkeypatch):
    monkeypatch.setenv("VERIFIER_SYNTHESIZER_URL", "http://synth:8204/synthesize")
    sent = []

    def handler(request):
        sent.append(request)
        return httpx.Response(200, json={"status": "ok", "answer": "30 days"})

    _mock_synthesizer(monkeypatch, handler)
    out = TestClient(api.app).post("/verify", json=RAG_OUTPUT).json()
    assert out["result"]["status"] == "ok"
    assert out["synthesizer"]["response"]["answer"] == "30 days"
    body = httpx.Response(200, content=sent[0].content).json()
    assert str(sent[0].url) == "http://synth:8204/synthesize"
    assert body["question"] == "What is the notice period?"
    assert body["verification"]["passed"] is True
    assert body["inputs"]["rag"]["chunks"][0]["content"] == "The notice period is 30 days."


def test_synthesizer_down_keeps_the_verdict(monkeypatch):
    monkeypatch.setenv("VERIFIER_SYNTHESIZER_URL", "http://synth:8204/synthesize")

    def handler(request):
        raise httpx.ConnectError("refused")

    _mock_synthesizer(monkeypatch, handler)
    out = TestClient(api.app).post("/verify", json=RAG_OUTPUT).json()
    assert out["result"]["status"] == "ok"
    assert "error" in out["synthesizer"]


def test_nothing_sent_without_url(monkeypatch):
    monkeypatch.delenv("VERIFIER_SYNTHESIZER_URL", raising=False)
    out = TestClient(api.app).post("/verify", json=RAG_OUTPUT).json()
    assert "synthesizer" not in out


def test_machine_gone_is_searched_again(monkeypatch):
    monkeypatch.delenv("VERIFIER_SYNTHESIZER_URL", raising=False)
    monkeypatch.setenv("VERIFIER_SYNTHESIZER_PATH", "/synthesize")
    urls = iter(["http://192.168.1.22:8204/synthesize", "http://192.168.1.23:8204/synthesize"])

    async def synthesizer_url(refresh=False):
        return next(urls)

    monkeypatch.setattr(api.discovery, "synthesizer_url", synthesizer_url)

    def handler(request):
        if request.url.host == "192.168.1.22":
            raise httpx.ConnectError("refused")
        return httpx.Response(200, json={"status": "ok", "answer": "30 days"})

    _mock_synthesizer(monkeypatch, handler)
    out = TestClient(api.app).post("/verify", json=RAG_OUTPUT).json()
    assert out["synthesizer"]["url"] == "http://192.168.1.23:8204/synthesize"
    assert out["synthesizer"]["status"] == 200
