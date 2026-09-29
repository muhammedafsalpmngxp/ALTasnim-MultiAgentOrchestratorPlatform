"""graph.ainvoke / astream end to end, with FakeChatModel and fake tools (no network)."""

import asyncio

import openai
import pytest
from langchain_core.runnables import RunnableLambda
from web_search_agent import llm
from web_search_agent.context import Context
from web_search_agent.graph import graph
from web_search_agent.nodes.plan_queries import SearchPlan
from web_search_agent.services import history
from web_search_agent.settings import get_settings

from utils import AgentTask
from utils.testing import run_agent_graph

QUESTION = "latest solid-state batteries"
FLOW = ["plan", "search", "extract", "chunk", "rerank", "verify"]


def task(objective: str = QUESTION, inputs: dict | None = None, **params) -> dict:
    return {"task": AgentTask(task_id="s1", objective=objective, params=params, inputs=inputs or {}).model_dump()}


def run(inputs: dict, context: Context | None = None) -> tuple[dict, dict]:
    """(step result for the orchestrator -> verifier, full run details kept for the UI)."""
    context = context or Context(trace_id="t-1")
    result = asyncio.run(graph.ainvoke(inputs, context=context))["result"]
    return result, history.get(context["trace_id"])


def steps(details: dict) -> dict:
    return {step["id"]: step for step in details["steps"]}


def good_plan():
    return SearchPlan(queries=["solid-state battery 2026", "solid-state battery 2026", "sulfide electrolyte"],
                      freshness="none")


def test_graph_has_no_summarizer_and_ends_with_sending_the_output():
    assert set(graph.get_graph().nodes) == {"__start__", "plan_queries", "search", "select_pages", "extract", "rank",
                                            "finalize", "send_output", "__end__"}


def test_step_result_is_only_the_question_and_the_top_3_contents(fake_web, fake_llm, monkeypatch):
    monkeypatch.setenv("WEB_SEARCH_CHUNK_SIZE_WORDS", "40")  # the shared article -> several passages
    monkeypatch.setenv("WEB_SEARCH_CHUNK_OVERLAP_WORDS", "5")
    get_settings.cache_clear()
    fake_llm.responses = {SearchPlan: good_plan()}  # 2 queries -> 3 pages -> more than 3 passages
    result, details = run(task(), Context(trace_id="t-1", top_k=8))

    assert set(result) == {"status", "summary", "question", "findings", "sources"}
    assert result["status"] == "ok" and result["question"] == QUESTION
    assert len(details["evidence"]) > 3 and len(result["findings"]) == 3
    assert [f["rank"] for f in result["findings"]] == [1, 2, 3]
    assert [f["content"] for f in result["findings"]] == [" ".join(e["content"].split())
                                                        for e in details["evidence"][:3]]
    assert set(result["findings"][0]) == {"rank", "title", "url", "content"}
    assert result["sources"] == [f["url"] for f in result["findings"]]
    assert result["summary"].startswith(f"Question: {QUESTION}\n\nTop 3 web results:\n\n[1] ")


def test_without_llm_returns_reranked_evidence(fake_web):
    _, details = run(task())

    assert details["trace_id"] == "t-1"
    assert details["search_queries"] == [QUESTION]
    assert details["reranker"] == "bm25"
    # citations contiguous, every cited source listed
    cited = {e["citation_id"] for e in details["evidence"]}
    assert cited == {c["citation_id"] for c in details["citations"]} == set(range(1, len(cited) + 1))
    assert "[1]" in details["context"]

    s = steps(details)
    assert list(s) == FLOW
    assert s["plan"]["status"] == "skipped"
    for step_id in ("search", "extract", "chunk", "rerank"):
        assert s[step_id]["status"] == "done"
    assert s["verify"]["status"] == "skipped"  # WEB_SEARCH_VERIFIER_PATH empty
    assert details["verification"] == {"status": "not_configured", "url": None}
    for step_id in ("search", "extract", "chunk", "rerank"):
        assert isinstance(s[step_id]["duration_s"], float)
    assert s["extract"]["detail"] == "1/2 pages extracted with Trafilatura"
    assert details["timings"]["total_s"] >= details["timings"]["rerank_s"]


def test_parallel_search_per_query_and_fetch_per_page(fake_web, fake_llm):
    fake_llm.responses = {SearchPlan: good_plan()}
    _, details = run(task())

    # duplicate planned query removed -> 2 parallel searches; shared page de-duplicated -> 3 unique pages fetched
    assert sorted(c["query"] for c in fake_web["search_calls"]) == ["solid-state battery 2026", "sulfide electrolyte"]
    assert len(fake_web["fetch_calls"]) == len(set(fake_web["fetch_calls"])) == 3
    assert details["search_queries"] == ["solid-state battery 2026", "sulfide electrolyte"]
    assert details["llm"] == {"planner_model": "gpt-4o-mini"}
    assert fake_llm.calls == [("fast", "gpt-4o-mini", "SearchPlan")]  # the only LLM call
    assert steps(details)["plan"]["items"] == details["search_queries"]


def test_region_and_domains_from_the_supervisor(fake_web):
    result, _ = run(task("Find iPhone price in Oman", query="iPhone price", region="Oman",
                         include_domains=["apple.com"]))
    assert result["question"] == "iPhone price in Oman"
    assert fake_web["search_calls"] == [{"query": "iPhone price in Oman", "freshness": None,
                                        "include_domains": ["apple.com"]}]


RAG_OUTPUT = {"status": "ok", "summary": "Internal policy: 30 days annual leave. UAE legal minimum not in documents.",
              "search_queries": ["UAE labour law annual leave days"]}


def test_rag_input_adds_its_queries_without_llm(fake_web):
    run(task("Compare our leave policy with UAE law", inputs={"s1": RAG_OUTPUT}))
    assert [c["query"] for c in fake_web["search_calls"]] == ["Compare our leave policy with UAE law",
                                                              "UAE labour law annual leave days"]


def test_rag_input_tells_the_planner_what_is_known(fake_web, fake_llm, monkeypatch):
    seen: list[str] = []
    fake_llm.responses = {SearchPlan: SearchPlan(queries=["UAE annual leave law"], freshness="none")}
    real = llm.structured

    def recording(tier, model, schema):
        runnable = real(tier, model, schema)

        async def call(messages):
            seen.append(messages[-1].content)
            return await runnable.ainvoke(messages)

        return RunnableLambda(call)

    monkeypatch.setattr(llm, "structured", recording)

    _, details = run(task("Compare our leave policy with UAE law", inputs={"s1": RAG_OUTPUT}))
    assert "Already found by earlier agents" in seen[0] and "30 days annual leave" in seen[0]
    assert "UAE labour law annual leave days" in seen[0]
    # planner first, then the RAG agent's query in the remaining slot
    assert details["search_queries"] == ["UAE annual leave law", "UAE labour law annual leave days"]
    assert steps(details)["plan"]["detail"].endswith("+ input from s1")


def test_stream_emits_flow_then_full_details(fake_web, fake_llm):
    fake_llm.responses = {SearchPlan: good_plan()}

    async def collect():
        return [chunk async for chunk in graph.astream(task(), context=Context(), stream_mode="custom")]

    events = asyncio.run(collect())
    assert events[0]["type"] == "steps" and [s["id"] for s in events[0]["steps"]] == FLOW
    assert events[-1]["type"] == "result"
    assert events[-1]["result"]["evidence"] and events[-1]["result"]["question"] == QUESTION
    updates = [(e["step"]["id"], e["step"]["status"]) for e in events if e["type"] == "step"]
    assert updates[:2] == [("plan", "running"), ("plan", "done")]
    assert ("search", "running") in updates and ("extract", "running") in updates
    assert [step_id for step_id, status in updates if status in ("done", "skipped")] == FLOW


def test_context_can_switch_the_planner_model(fake_web, fake_llm):
    fake_llm.responses = {SearchPlan: good_plan()}
    _, details = run(task(), Context(trace_id="t-1", fast_model="gpt-test-fast"))
    assert details["llm"] == {"planner_model": "gpt-test-fast"}
    assert fake_llm.calls == [("fast", "gpt-test-fast", "SearchPlan")]


def test_transient_llm_error_is_retried_by_retry_policy(fake_web, fake_llm):
    transient = openai.APIConnectionError(request=None)  # type: ignore[arg-type]
    fake_llm.responses = {SearchPlan: [transient, good_plan()]}
    _, details = run(task())
    assert details["search_queries"] == ["solid-state battery 2026", "sulfide electrolyte"]
    assert [c[2] for c in fake_llm.calls].count("SearchPlan") == 2


def test_non_transient_planner_failure_falls_back_to_the_question(fake_web, fake_llm):
    fake_llm.responses = {SearchPlan: ValueError("bad schema")}
    result, details = run(task())
    assert result["status"] == "ok" and result["findings"]
    assert details["search_queries"] == [QUESTION]
    assert steps(details)["plan"]["status"] == "failed"
    assert any("query planning failed" in w for w in details["warnings"])


def test_no_results_fails_the_step_so_the_supervisor_can_replan(fake_web):
    fake_web["no_results"]()
    result, details = run(task("nothing matches this"))
    s = steps(details)
    assert result == {"status": "failed", "summary": "No web results for: nothing matches this",
                      "question": "nothing matches this", "findings": [], "sources": []}
    assert s["search"]["status"] == "failed"
    assert all(s[i]["status"] == "skipped" for i in ("extract", "chunk", "rerank"))
    assert fake_web["fetch_calls"] == []


def test_sample_provider_ranks_snippets_without_downloading(offline):
    result = run_agent_graph(graph, AgentTask(task_id="s1", objective="iPhone price"))  # sync graph.invoke
    assert result["status"] == "ok" and len(result["findings"]) == 3
    details = history.get(history.recent(1)[0]["trace_id"])
    assert details["provider_used"] == "sample" and details["reranker"] == "bm25"
    assert offline["fetch_calls"] == []


def test_runs_are_recorded_for_the_ui_history(fake_web):
    run(task())
    recent = history.recent(5)[0]
    assert recent["trace_id"] == "t-1" and recent["source_agent"] == "orchestrator"
    assert recent["preview"]
    assert history.get("t-1")["citations"]


@pytest.mark.parametrize("top_k", [1, 2])
def test_top_k_limits_evidence_and_the_top_contents(fake_web, top_k):
    result, details = run(task(), Context(trace_id="t-1", top_k=top_k))
    assert len(details["evidence"]) <= top_k and len(result["findings"]) <= top_k


def test_a_whole_run_makes_no_blocking_calls_on_the_event_loop(fake_web, fake_llm):
    """langgraph dev (blockbuster) rejects blocking I/O in the event loop; run the full graph under the same check."""
    blockbuster = pytest.importorskip("blockbuster")
    fake_llm.responses = {SearchPlan: good_plan()}
    get_settings()  # loaded at import time in the server

    async def go():
        with blockbuster.blockbuster_ctx():
            return await graph.ainvoke(task(), context=Context(trace_id="t-bb"))

    result = asyncio.run(go())["result"]
    assert result["status"] == "ok"
    details = history.get("t-bb")
    assert steps(details)["plan"]["status"] == "done", steps(details)["plan"]
    assert not [w for w in details["warnings"] if "Blocking" in w]
