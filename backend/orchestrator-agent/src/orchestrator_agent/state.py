"""Orchestrator state. All values are plain dicts/lists so the Angular UI can read
them through the LangGraph SDK (``threads.getState``) without custom decoding."""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


def merge_dict(left: dict | None, right: dict | None) -> dict:
    """Reducer: merge by key; a value of None deletes the key (used on replan / new turn)."""
    out = dict(left or {})
    for key, value in (right or {}).items():
        if value is None:
            out.pop(key, None)
        else:
            out[key] = value
    return out


class OrchestratorInput(TypedDict, total=False):
    """What callers send: ``{"request": "..."}`` (Angular) or chat ``messages``."""

    request: str
    messages: Annotated[list[AnyMessage], add_messages]


class OrchestratorState(OrchestratorInput, total=False):
    # Plan JSON created by the supervisor and completed by plan_guard (Plan.model_dump()).
    plan: dict[str, Any] | None
    # Per-step results, keyed by step id (AgentResult.model_dump()). Parallel-safe reducer.
    results: Annotated[dict[str, Any], merge_dict]
    # Per-step live status for the Runs UI (StepStatus.model_dump()).
    step_status: Annotated[dict[str, Any], merge_dict]
    # Why the last plan failed; given to the supervisor when replanning.
    feedback: list[str]
    replans: int
    clarifications: list[str]
    pending_question: str | None
    final: str | None
