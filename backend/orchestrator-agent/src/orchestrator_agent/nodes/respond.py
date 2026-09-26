"""respond: the final answer to the user in chat."""

from __future__ import annotations

from langchain_core.messages import AIMessage

from orchestrator_agent.state import OrchestratorState
from utils import Plan
from utils.events import emit


def respond(state: OrchestratorState) -> dict:
    text = state.get("final")
    if not text:
        plan = Plan.model_validate(state["plan"])
        results = state.get("results", {})
        lines = []
        for step in plan.steps:
            res = results.get(step.id)
            if res and step.added_by == "supervisor":
                lines.append(f"{step.agent}: {res['output'].get('summary', res['status'])}")
        warnings = [w for s in plan.steps if s.agent == "verifier" and s.id in results
                    for w in results[s.id]["output"].get("warnings", [])]
        text = "\n\n".join(lines) or "Done."
        if warnings:
            text += "\n\nNote: " + "; ".join(warnings)
        # TODO(platform): with get_model("standard"), turn the results into a natural answer.
    emit("final", text=text)
    return {"final": text, "messages": [AIMessage(text)]}
