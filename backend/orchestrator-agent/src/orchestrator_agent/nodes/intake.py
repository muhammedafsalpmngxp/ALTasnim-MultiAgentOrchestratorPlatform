"""Start of every turn: take the new request and reset per-turn fields.

A thread can hold many turns (chat). Plan/results of the previous turn are
cleared here so each request is planned from scratch.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from orchestrator_agent.state import OrchestratorState


def intake(state: OrchestratorState) -> dict:
    messages = state.get("messages", [])
    last = messages[-1] if messages else None
    update: dict = {}

    if last is not None and last.type == "human" and last.content != state.get("request"):
        request = str(last.content)  # chat input: {"messages": [...]}
    else:
        request = state.get("request", "")
        update["messages"] = [HumanMessage(request)]  # API input: {"request": "..."}

    return {
        **update,
        "request": request,
        "plan": None,
        "results": {k: None for k in state.get("results", {})},
        "step_status": {k: None for k in state.get("step_status", {})},
        "feedback": [],
        "replans": 0,
        "clarifications": [],
        "pending_question": None,
        "final": None,
    }
