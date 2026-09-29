"""End-to-end flows through the real orchestrator graph with the real agent graphs
(transport=local, in-memory checkpointers, no LLM, no network)."""

import uuid

import pytest
from communication_agent.card import CARD as COMM
from communication_agent.graph import graph as comm_graph
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from orchestrator_agent.deps import Deps
from orchestrator_agent.graph import build_graph
from orchestrator_agent.planning.rule_planner import RulePlanner
from orchestrator_agent.registry import AgentRegistry
from orchestrator_agent.settings import Policies
from verifier_agent.card import CARD as VERIFIER
from verifier_agent.graph import graph as verifier_graph
from web_search_agent.card import CARD as SEARCH
from web_search_agent.graph import graph as search_graph

from utils.testing import build_stub_agent


def make_graph(**overrides):
    agents = {"web_search": (SEARCH, search_graph), "communication": (COMM, comm_graph),
              "verifier": (VERIFIER, verifier_graph), **overrides}
    deps = Deps(registry=AgentRegistry.from_graphs(agents), planner=RulePlanner(), policies=Policies())
    return build_graph(deps=deps, checkpointer=InMemorySaver())


def new_thread():
    return {"configurable": {"thread_id": str(uuid.uuid4())}}


@pytest.fixture
def sent(monkeypatch):
    emails = []
    monkeypatch.setattr("communication_agent.nodes.send.send_email", lambda d: emails.append(d) or f"id{len(emails)}")
    return emails


async def test_q1_price_question_search_then_verify():
    graph, cfg = make_graph(), new_thread()
    out = await graph.ainvoke({"request": "What is the price of iPhone?"}, cfg)

    assert "__interrupt__" not in out
    assert [s["id"] for s in out["plan"]["steps"]] == ["s1", "v_final"]
    assert out["results"]["s1"]["status"] == "ok"
    assert out["results"]["v_final"]["output"]["passed"] is True
    assert "web_search" in out["final"]
    assert {v["status"] for v in out["step_status"].values()} == {"done"}


async def test_q2_price_then_email_waits_for_approval_then_sends_once(sent):
    graph, cfg = make_graph(), new_thread()
    out = await graph.ainvoke({"request": "check the price of iphone then share the mail to rijin@gmail.com"}, cfg)

    # Paused: the communication agent's approval request surfaced in the orchestrator.
    pending = out["__interrupt__"][0].value
    assert pending["kind"] == "agent_approval" and pending["agent"] == "communication"
    assert pending["request"]["draft"]["to"] == ["rijin@gmail.com"]
    assert out["results"]["v_s2"]["status"] == "ok"  # verified before the human sees it
    assert sent == []

    out = await graph.ainvoke(Command(resume={"action": "approve"}), cfg)
    assert "__interrupt__" not in out
    assert len(sent) == 1 and sent[0].to == ["rijin@gmail.com"]
    assert out["results"]["s2"]["output"]["delivery"] == "sent"
    assert "sent to rijin@gmail.com" in out["final"]


async def test_q2_reject_stops_without_sending(sent):
    graph, cfg = make_graph(), new_thread()
    await graph.ainvoke({"request": "check the price of iphone then share the mail to rijin@gmail.com"}, cfg)
    out = await graph.ainvoke(Command(resume={"action": "reject", "reason": "not now"}), cfg)
    assert sent == []
    assert out["final"].startswith("Stopped")


async def test_q3_compare_runs_both_searches_in_the_same_wave(sent):
    graph, cfg = make_graph(), new_thread()
    waves = []
    async for chunk in graph.astream(
        {"request": "Compare iPhone price in Oman and UAE and email it to rijin@gmail.com"},
        cfg, stream_mode="debug",
    ):
        if chunk["type"] == "task" and chunk["payload"]["name"] == "run_agent":
            waves.append((chunk["step"], chunk["payload"]["input"]["step"]["id"]))

    first_wave = {sid for step, sid in waves if step == min(s for s, _ in waves)}
    assert first_wave == {"s1", "s2"}  # parallel
    await graph.ainvoke(Command(resume={"action": "approve"}), cfg)
    assert "Oman" in sent[0].body and "UAE" in sent[0].body


async def test_missing_recipient_asks_user_then_continues(sent):
    graph, cfg = make_graph(), new_thread()
    out = await graph.ainvoke({"request": "check the iPhone price and email it"}, cfg)
    assert out["__interrupt__"][0].value["kind"] == "clarification"

    out = await graph.ainvoke(Command(resume="rijin@gmail.com"), cfg)
    assert out["__interrupt__"][0].value["kind"] == "agent_approval"
    await graph.ainvoke(Command(resume={"action": "approve"}), cfg)
    assert sent[0].to == ["rijin@gmail.com"]


async def test_failing_agent_triggers_replan_then_stops_at_limit():
    broken = build_stub_agent("web_search", {"status": "failed", "summary": "search backend down"})
    graph, cfg = make_graph(web_search=(SEARCH, broken)), new_thread()
    out = await graph.ainvoke({"request": "What is the price of iPhone?"}, cfg)
    assert out["replans"] == Policies().max_replans
    assert "could not complete" in out["final"]
    assert "search backend down" in out["final"]


async def test_second_turn_on_same_thread_is_planned_fresh():
    graph, cfg = make_graph(), new_thread()
    await graph.ainvoke({"request": "What is the price of iPhone?"}, cfg)
    out = await graph.ainvoke({"request": "hello"}, cfg)
    assert out["plan"] is None and out["results"] == {}
    assert "I can search the web" in out["final"]
