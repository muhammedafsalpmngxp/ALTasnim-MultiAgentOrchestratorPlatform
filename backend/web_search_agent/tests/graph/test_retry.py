""""Retry": send another request to the output agents with a saved run - no search, page fetch, rerank or LLM call."""

import asyncio
import json
import os

import pytest
from fastapi.testclient import TestClient
from web_search_agent import api
from web_search_agent.context import Context
from web_search_agent.graph import graph
from web_search_agent.nodes.plan_queries import SearchPlan
from web_search_agent.services import checkpoints, handoff, history
from web_search_agent.settings import get_settings

from utils import AgentTask

VERDICT = {"status": "ok", "passed": True, "issues": [], "warnings": [], "summary": "Verification passed"}


def run(trace_id: str = "t-retry") -> tuple[dict, dict]:
    inputs = {"task": AgentTask(task_id="s1", objective="latest solid-state batteries").model_dump()}
    result = asyncio.run(graph.ainvoke(inputs, context=Context(trace_id=trace_id)))["result"]
    return result, history.get(trace_id)


def step(details: dict, step_id: str) -> dict:
    return next(s for s in details["steps"] if s["id"] == step_id)


def retry(trace_id: str = "t-retry"):
    with TestClient(api.app) as client:
        return client.post("/custom/retry", params={"trace_id": trace_id})


@pytest.fixture
def paths(monkeypatch):
    monkeypatch.setenv("WEB_SEARCH_VERIFIER_PATH", "/verify")
    get_settings.cache_clear()


def test_there_is_no_checkpoint_step_or_node(fake_web):
    _, details = run()
    assert "checkpoint" not in {s["id"] for s in details["steps"]}
    assert "checkpoint" not in graph.get_graph().nodes


def test_every_run_is_saved_for_retry(fake_web):
    _, details = run()
    saved = checkpoints.load("t-retry")
    state = saved["state"]
    assert state["query"] == "latest solid-state batteries" and state["evidence"] == details["evidence"]
    assert state["task"]["task_id"] == "s1" and state["step_state"]["rerank"]["status"] == "done"
    assert saved["details"]["trace_id"] == "t-retry"  # the finished run is kept with it
    assert "logs" not in str(checkpoints.directory())  # tests write to a temp dir


def test_retry_sends_again_without_search_or_llm(fake_web, fake_llm, paths, monkeypatch):
    fake_llm.responses = {SearchPlan: SearchPlan(queries=["solid-state battery 2026"], freshness="none")}
    sends = []

    async def deliver(step_id, result):
        sends.append((step_id, result))
        if len(sends) == 1:
            return [handoff._record("http://192.168.1.25:8203/verify", error=OSError("verifier down"))]
        return [handoff._record("http://192.168.1.25:8203/verify", VERDICT)]

    monkeypatch.setattr(handoff, "deliver", deliver)
    first_result, first = run()
    assert step(first, "verify")["status"] == "failed"
    searches, fetches, llm_calls = len(fake_web["search_calls"]), len(fake_web["fetch_calls"]), len(fake_llm.calls)

    response = retry()
    assert response.status_code == 200
    again = response.json()

    # only another request to the output agents: no new search, page fetch or LLM call
    assert (len(fake_web["search_calls"]), len(fake_web["fetch_calls"]), len(fake_llm.calls)) == (
        searches, fetches, llm_calls)
    assert sends[1] == ("s1", first_result)  # the same output (question + top 3)
    assert step(again, "verify")["status"] == "done" and again["verification"]["passed"] is True
    assert again["retries"] == 1 and again["retried_at"]
    assert again["evidence"] == first["evidence"] and step(again, "rerank") == step(first, "rerank")
    assert history.get("t-retry")["retries"] == 1
    assert checkpoints.load("t-retry")["details"]["retries"] == 1  # also after a restart

    assert retry().json()["retries"] == 2


def test_a_run_is_saved_before_sending_so_a_crash_can_be_retried(fake_web, paths, monkeypatch):
    async def crash(step_id, result):
        assert checkpoints.load("t-retry") is not None  # already saved
        raise RuntimeError("network stack exploded")

    monkeypatch.setattr(handoff, "deliver", crash)
    result, details = run()
    assert result["status"] == "ok" and step(details, "verify")["status"] == "failed"

    async def deliver(step_id, result):
        return [handoff._record("http://192.168.1.25:8203/verify", VERDICT)]

    monkeypatch.setattr(handoff, "deliver", deliver)
    assert retry().json()["verification"]["passed"] is True


def test_retry_works_after_a_restart(fake_web, paths, monkeypatch):
    async def deliver(step_id, result):
        return [handoff._record("http://192.168.1.25:8203/verify", VERDICT)]

    monkeypatch.setattr(handoff, "deliver", deliver)
    run()
    saved = checkpoints.load("t-retry")
    checkpoints.save("t-retry", {"state": saved["state"]})  # only the state is on disk
    history.clear()  # the in-memory history is gone

    again = retry().json()
    assert again["trace_id"] == "t-retry" and again["question"] == "latest solid-state batteries"
    assert again["verification"]["passed"] is True and len(again["findings"]) <= 3


def test_retry_uses_the_current_top_n(fake_web, paths, monkeypatch):
    sent = []

    async def deliver(step_id, result):
        sent.append(result)
        return [handoff._record("http://192.168.1.25:8203/verify", VERDICT)]

    monkeypatch.setattr(handoff, "deliver", deliver)
    run()
    monkeypatch.setenv("WEB_SEARCH_RESULT_TOP_N", "1")
    get_settings.cache_clear()
    retry()
    assert len(sent[0]["findings"]) > 1 and len(sent[1]["findings"]) == 1


def test_runs_without_results_can_be_retried_too(fake_web):
    fake_web["no_results"]()
    result, _ = run("t-empty")
    assert result["status"] == "failed"
    assert checkpoints.load("t-empty")["state"]["evidence"] in (None, [])
    assert retry("t-empty").status_code == 200


def test_unknown_or_unsafe_trace_ids(fake_web):
    assert retry("nope").status_code == 404
    assert retry("../../etc/passwd").status_code == 404
    with pytest.raises(ValueError):
        checkpoints.save("../x", {})


def test_old_saved_runs_are_pruned(monkeypatch):
    monkeypatch.setenv("WEB_SEARCH_CHECKPOINT_KEEP", "2")
    get_settings.cache_clear()
    for i in range(4):
        path = checkpoints.save(f"run-{i}", {"state": {"i": i}})
        os.utime(path, ns=(1_000_000_000 * (i + 1),) * 2)  # distinct times (saves can share one clock tick)
    checkpoints.save("run-4", {"state": {"i": 4}})  # newest (now) -> prunes to the 2 newest
    kept = sorted(json.loads(p.read_text())["state"]["i"] for p in checkpoints.directory().glob("*.json"))
    assert kept == [3, 4]
