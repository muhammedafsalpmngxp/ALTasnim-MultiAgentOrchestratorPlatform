"""plan_guard: the last check that the supervisor's plan can run (code, no LLM), then hands it to progress.

The supervisor's LLM already fixed its plan against the same check (planning/llm_supervisor.py); a plan that
still cannot run (e.g. an agent went down meanwhile) ends the request with the reasons.
Supervisor v1 has no guardrails here (inserted verifier / approval steps come back in v2).
"""

from __future__ import annotations

from typing import Literal

from langgraph.types import Command

from orchestrator_agent.deps import DepsProvider
from orchestrator_agent.planning.validate import check_plan
from orchestrator_agent.state import OrchestratorState
from utils import Plan, StepStatus
from utils.events import emit, now_iso


def make_plan_guard(get_deps: DepsProvider):
    def plan_guard(state: OrchestratorState) -> Command[Literal["progress", "respond"]]:
        plan = Plan.model_validate(state["plan"])
        errors = check_plan(plan, get_deps().registry.cards())
        if errors:
            return Command(goto="respond", update={
                "final": "I could not build a valid plan for this request:\n- " + "\n- ".join(errors)})

        results = state.get("results", {})
        queued = {
            s.id: StepStatus(status="queued", agent=s.agent, updated_at=now_iso()).model_dump()
            for s in plan.steps if s.id not in results
        }
        emit("plan", plan=plan.model_dump())
        return Command(goto="progress", update={"step_status": queued})

    return plan_guard
