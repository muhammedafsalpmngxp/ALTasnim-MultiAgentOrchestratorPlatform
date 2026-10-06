"""hitl_gate: a plan step that waits for a human (``interrupt``). Not an LLM.

Resume with ``Command(resume={"action": "approve" | "reject" | "revise", "comment": "..."})``.
"revise" sends the plan back to the supervisor with the comment as feedback.
"""

from __future__ import annotations

from langgraph.types import interrupt

from utils import AgentResult, Step, StepStatus
from utils.events import emit, now_iso


def hitl_gate(payload: dict) -> dict:
    step = Step.model_validate(payload["step"])
    emit("step_waiting_approval", step_id=step.id, agent="hitl")
    decision = interrupt({"kind": "approval", "step_id": step.id, "objective": step.objective,
                          "context": payload.get("deps", {})})
    decision = decision if isinstance(decision, dict) else {"action": str(decision)}
    action = decision.get("action", "reject")
    status = {"approve": "ok", "revise": "revise"}.get(action, "rejected")
    comment = decision.get("comment", "")
    result = AgentResult(step_id=step.id, agent="hitl", status=status,
                         output={"decision": decision, "summary": f"Human {action}: {comment}".strip(": ")})
    ui = {"ok": "done", "revise": "failed", "rejected": "rejected"}[status]
    return {"results": {step.id: result.model_dump()},
            "step_status": {step.id: StepStatus(status=ui, agent="hitl", updated_at=now_iso()).model_dump()}}
