import importlib.util
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_openai import ChatOpenAI
from synthesizer_agent.api import app

from synthesizer_agent import agent

client = TestClient(app)
QUESTION = "What is the iPhone 16 price in Oman?"
VERIFIED = {
    "web_search": {"status": "ok", "summary": "Apple: iPhone 16 from OMR 329", "sources": ["https://apple.com/om"]},
    "verifier": {"status": "ok", "passed": True, "summary": "Verification passed"},
}


@pytest.fixture
def llm(monkeypatch):
    """Fake LLM that replies with the given text and remembers the prompt it got."""
    prompts = []

    class Fake(FakeListChatModel):
        def invoke(self, messages, *args, **kwargs):
            # the agent sends [("system", ...), ("human", ...)]; keep one text for the asserts
            prompts.append(messages if isinstance(messages, str) else "\n".join(text for _, text in messages))
            return super().invoke(messages, *args, **kwargs)

    def use(reply: str) -> list:
        monkeypatch.setattr(agent, "_model", lambda: Fake(responses=[reply]))
        return prompts

    return use


@pytest.fixture
def no_llm(monkeypatch):
    monkeypatch.setattr(agent, "_model", lambda: None)


# ---- API ----

def test_ok_and_card():
    assert client.get("/ok").json() == {"ok": True}
    assert client.get("/card").json()["name"] == "synthesizer"


def test_synthesize_answers_from_question_and_inputs(llm):
    prompts = llm("<think>hmm</think>The iPhone 16 costs OMR 329.")
    res = client.post("/synthesize", json={"question": QUESTION, "inputs": VERIFIED})

    assert res.status_code == 200
    assert res.json() == {"status": "ok", "summary": "The iPhone 16 costs OMR 329.",
                          "answer": "The iPhone 16 costs OMR 329.", "sources": ["https://apple.com/om"]}
    assert QUESTION in prompts[0] and "OMR 329" in prompts[0] and "Verification passed" in prompts[0]


def test_any_input_shape_is_passed_to_the_llm(llm):
    prompts = llm("ok")
    inputs = {"a": "plain text", "b": {"chunks": [{"doc": "hr.pdf", "text": "30 days leave"}]}, "c": [1, 2]}
    client.post("/synthesize", json={"question": "q", "inputs": inputs})
    assert "plain text" in prompts[0] and "30 days leave" in prompts[0]


def test_without_a_question_the_llm_works_it_out(llm):
    prompts = llm("ok")
    res = client.post("/synthesize", json={"inputs": VERIFIED})
    assert res.status_code == 200
    assert "No question was given" in prompts[0] and "OMR 329" in prompts[0]


def test_without_llm_returns_the_input_summaries(no_llm):
    res = client.post("/synthesize", json={"question": QUESTION, "inputs": {**VERIFIED, "x": "plain text"}})
    assert res.json()["answer"] == "Apple: iPhone 16 from OMR 329\n\nVerification passed\n\nplain text"


def test_no_inputs_fails(no_llm):
    assert client.post("/synthesize", json={"question": QUESTION}).json()["status"] == "failed"


# ---- LLM settings (SYNTHESIZER_OPENAI_* in backend/.env) ----

@pytest.fixture
def fresh_model(monkeypatch):
    """Rebuild the LLM from the env vars set in the test."""
    for name in ("SYNTHESIZER_OPENAI_MODEL", "SYNTHESIZER_OPENAI_BASE_URL", "SYNTHESIZER_OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    agent._model.cache_clear()
    yield
    agent._model.cache_clear()


def test_openai_settings_are_used(monkeypatch, fresh_model):
    monkeypatch.setenv("SYNTHESIZER_OPENAI_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("SYNTHESIZER_OPENAI_BASE_URL", "https://my-gateway.example.com/v1")
    monkeypatch.setenv("SYNTHESIZER_OPENAI_API_KEY", "sk-test")

    model = agent._model()
    assert isinstance(model, ChatOpenAI)
    assert model.model_name == "gpt-4o-mini"
    assert model.openai_api_base == "https://my-gateway.example.com/v1"
    assert model.openai_api_key.get_secret_value() == "sk-test"


def test_no_model_means_no_llm(fresh_model):
    assert agent._model() is None


def test_openai_without_a_key_means_no_llm(monkeypatch, fresh_model):
    monkeypatch.setenv("SYNTHESIZER_OPENAI_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("SYNTHESIZER_OPENAI_BASE_URL", "https://api.openai.com/v1")
    assert agent._model() is None


def test_local_server_needs_no_key(monkeypatch, fresh_model):
    monkeypatch.setenv("SYNTHESIZER_OPENAI_MODEL", "qwen3:4b")
    monkeypatch.setenv("SYNTHESIZER_OPENAI_BASE_URL", "http://localhost:11434/v1")
    assert agent._model().openai_api_base == "http://localhost:11434/v1"


# ---- run history for the UI ----

@pytest.fixture(autouse=True)
def empty_history():
    client.delete("/runs")


def test_each_request_is_remembered_newest_first(no_llm):
    client.post("/synthesize", json={"question": "first", "inputs": VERIFIED})
    client.post("/synthesize", json={"question": "second", "inputs": VERIFIED})

    runs = client.get("/runs").json()
    assert [r["question"] for r in runs] == ["second", "first"]
    assert runs[0]["state"] == "done" and runs[0]["inputs"] == VERIFIED
    assert runs[0]["result"]["status"] == "ok" and runs[0]["seconds"] is not None
    assert "prompt" not in runs[0]  # only in GET /runs/{id}


def test_one_run_shows_the_prompt_and_llm(llm):
    llm("answer")
    client.post("/synthesize", json={"question": QUESTION, "inputs": VERIFIED})
    run_id = client.get("/runs").json()[0]["id"]

    run = client.get(f"/runs/{run_id}").json()
    assert QUESTION in run["prompt"] and "OMR 329" in run["prompt"]
    assert run["llm"]["model"]
    assert client.get("/runs/unknown").status_code == 404


def test_llm_error_is_502_and_recorded(monkeypatch):
    class Broken:
        model_name = "broken"

        def invoke(self, *args, **kwargs):
            raise ConnectionError("LLM server not running")

    monkeypatch.setattr(agent, "_model", lambda: Broken())
    res = client.post("/synthesize", json={"question": QUESTION, "inputs": VERIFIED})

    assert res.status_code == 502 and "LLM server not running" in res.json()["detail"]
    assert client.get("/runs").json()[0]["state"] == "error"


def test_clear_history():
    client.post("/synthesize", json={"question": QUESTION, "inputs": VERIFIED})
    client.delete("/runs")
    assert client.get("/runs").json() == []


def test_cors_allows_the_ui():
    res = client.options("/synthesize", headers={"Origin": "http://localhost:4304",
                                                 "Access-Control-Request-Method": "POST"})
    assert res.headers.get("access-control-allow-origin") == "http://localhost:4304"


# ---- receives anything: any path, any body ----

def test_any_path_is_answered_and_the_question_is_found(llm):
    prompts = llm("It costs OMR 329.")
    body = {"query": QUESTION, "chunks": [{"text": "Apple: iPhone 16 from OMR 329", "url": "https://apple.com/om"}]}
    res = client.post("/verify", json=body)

    assert res.status_code == 200 and res.json()["answer"] == "It costs OMR 329."
    assert res.json()["sources"] == ["https://apple.com/om"]  # "url" fields found anywhere
    assert QUESTION in prompts[0] and "No question was given" not in prompts[0]
    run = client.get("/runs").json()[0]
    assert run["endpoint"] == "POST /verify" and run["question"] == QUESTION
    assert run["inputs"] == {"chunks": body["chunks"]}


def test_question_inside_task_is_found(llm):
    prompts = llm("ok")
    client.put("/", json={"task": {"objective": QUESTION, "inputs": {"s1": "data"}}})
    assert QUESTION in prompts[0]
    assert client.get("/runs").json()[0]["endpoint"] == "PUT /"


def test_plain_text_and_lists_are_accepted(llm):
    prompts = llm("ok")
    assert client.post("/anything", content="Apple Oman: iPhone 16 from OMR 329",
                       headers={"Content-Type": "text/plain"}).status_code == 200
    assert client.post("/anything", json=["chunk one", "chunk two"]).status_code == 200
    assert "OMR 329" in prompts[0] and "chunk two" in prompts[1]


def test_empty_request_fails_politely(no_llm):
    res = client.post("/whatever")
    assert res.status_code == 200 and res.json()["status"] == "failed"


def test_unknown_get_answers_ok_instead_of_404():
    res = client.get("/verify")
    assert res.status_code == 200 and res.json()["agent"] == "synthesizer"


def test_catch_all_does_not_hide_the_real_routes():
    assert client.get("/docs").status_code == 200
    assert client.get("/card").json()["name"] == "synthesizer"
    assert isinstance(client.get("/runs").json(), list)


# ---- prompt quality ----

def test_prompt_has_rules_and_todays_date_but_asks_for_no_citations(llm):
    prompts = llm("ok")
    body = {"question": "Who is the current chief minister?",
            "chunks": [{"text": "A", "url": "https://a.example"}, {"text": "B", "url": "https://b.example"}]}
    client.post("/synthesize", json=body)

    prompt = prompts[0]
    assert date.today().strftime("%d %B %Y") in prompt              # "current" = as of today
    assert "Short and direct" in prompt and "Never guess" in prompt
    assert "No citations or links" in prompt
    assert "[1] https://a.example" not in prompt                    # no numbered source list to cite


def test_citation_marks_are_removed_from_the_answer(llm):
    llm("Portugal won **2-1** on September 27, 2026 [1][2]. Ronaldo scored twice [1, 3].")
    answer = client.post("/synthesize", json={"question": QUESTION, "inputs": VERIFIED}).json()["answer"]
    assert answer == "Portugal won **2-1** on September 27, 2026. Ronaldo scored twice."


def test_the_ui_sees_system_and_user_parts(llm):
    llm("ok")
    client.post("/synthesize", json={"question": QUESTION, "inputs": VERIFIED})
    run = client.get(f"/runs/{client.get('/runs').json()[0]['id']}").json()
    assert "===== SYSTEM =====" in run["prompt"] and "===== HUMAN =====" in run["prompt"]


# ---- port from backend/.env ----

def test_run_py_reads_host_and_port_from_env(monkeypatch):
    monkeypatch.setenv("SYNTHESIZER_PORT", "9123")
    monkeypatch.setenv("SYNTHESIZER_HOST", "127.0.0.1")
    monkeypatch.setenv("SYNTHESIZER_RELOAD", "false")
    spec = importlib.util.spec_from_file_location("run", Path(__file__).resolve().parents[1] / "run.py")
    run = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run)
    assert run.settings() == {"host": "127.0.0.1", "port": 9123, "reload": False}


def test_graph_follows_the_agent_contract(monkeypatch):
    from synthesizer_agent.graph import graph

    monkeypatch.setattr(agent, "_model", lambda: None)  # no LLM: the answer is the inputs' summaries
    assert set(graph.get_input_jsonschema()["properties"]) == {"task"}
    assert set(graph.get_output_jsonschema()["properties"]) == {"result"}
    out = graph.invoke({"task": {"task_id": "s2", "objective": "Write the final answer",
                                 "params": {"question": QUESTION}, "inputs": VERIFIED}})
    assert out["result"]["status"] == "ok"
    assert "OMR 329" in out["result"]["summary"]
    assert client.get("/runs").json()[0]["question"] == QUESTION  # listed like the HTTP calls


def test_langgraph_server_drops_only_the_catch_all_routes(monkeypatch):
    import importlib

    monkeypatch.setattr(app.router, "routes", list(app.router.routes))  # the original list comes back after
    from synthesizer_agent import server

    importlib.reload(server)
    paths = {getattr(r, "path", None) for r in server.app.router.routes}
    assert "/{path:path}" not in paths  # would hide the LangGraph API (/threads, /assistants, ...)
    assert {"/synthesize", "/card", "/ok", "/runs"} <= paths
