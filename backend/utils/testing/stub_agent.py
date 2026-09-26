"""Stub agent graphs, so a team can run the full flow before other agents exist.

Example: register a stub instead of a real agent in the orchestrator's agent config::

    from utils.testing import build_stub_agent
    graph = build_stub_agent("data", {"status": "ok", "summary": "Q3 revenue: 1.2M (stub)"})
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from utils.contracts import AgentInput, AgentOutput


class _StubState(AgentInput, AgentOutput):
    pass


def build_stub_agent(name: str, result: dict[str, Any] | None = None):
    payload = result or {"status": "ok", "summary": f"{name} stub result"}

    def respond(state: _StubState) -> dict:
        return {"result": {**payload, "echo_objective": state["task"]["objective"]}}

    builder = StateGraph(_StubState, input_schema=AgentInput, output_schema=AgentOutput)
    builder.add_node("respond", respond)
    builder.add_edge(START, "respond")
    builder.add_edge("respond", END)
    return builder.compile(name=f"{name}_stub")
