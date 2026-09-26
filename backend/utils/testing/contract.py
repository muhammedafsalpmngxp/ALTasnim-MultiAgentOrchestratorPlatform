"""Contract checks. Every agent's tests/contract/test_contract.py calls these.

If an agent passes ``assert_agent_contract``, the orchestrator can plan with it
and run it.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph

from utils.contracts import AgentCard, AgentTask

_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


def assert_agent_contract(card: AgentCard, graph: CompiledStateGraph, sample_task: AgentTask) -> dict[str, Any]:
    """Validate the card and run the graph once with ``sample_task``.

    Returns the agent's ``result`` so the caller can add agent-specific asserts.
    """
    assert _NAME.match(card.name), f"card.name must be snake_case, got {card.name!r}"
    assert _SEMVER.match(card.version), f"card.version must be semver, got {card.version!r}"
    for field in ("description", "when_to_use", "when_not_to_use"):
        assert getattr(card, field).strip(), f"card.{field} must not be empty"
    assert len(card.examples) >= 2, "card needs at least 2 examples (the supervisor plans from them)"

    input_keys = set(graph.get_input_jsonschema().get("properties", {}))
    output_keys = set(graph.get_output_jsonschema().get("properties", {}))
    assert input_keys == {"task"}, f"graph input schema must be exactly {{'task'}}, got {input_keys}"
    assert output_keys == {"result"}, f"graph output schema must be exactly {{'result'}}, got {output_keys}"

    result = run_agent_graph(graph, sample_task, auto_approve=True)
    assert result.get("status") in {"ok", "failed", "rejected"}, f"result.status invalid: {result}"
    assert isinstance(result.get("summary"), str) and result["summary"], "result.summary must be a non-empty string"
    return result


def run_agent_graph(graph: CompiledStateGraph, task: AgentTask, auto_approve: bool = False) -> dict[str, Any]:
    """Run an agent graph in-process with a fresh checkpointer.

    With ``auto_approve=True``, any ``interrupt()`` is resumed with
    ``{"action": "approve"}``, so agents with internal approval complete.
    """
    from langgraph.types import Command

    compiled = graph.copy(update={"checkpointer": InMemorySaver()})
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    out = compiled.invoke({"task": task.model_dump()}, config)
    for _ in range(5):
        if "__interrupt__" not in out or not auto_approve:
            break
        out = compiled.invoke(Command(resume={"action": "approve"}), config)
    return out.get("result", {})
