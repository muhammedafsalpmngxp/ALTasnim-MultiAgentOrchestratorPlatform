"""plan_guard: validate the supervisor's plan and add policy steps (code, no LLM)."""

from __future__ import annotations

from typing import Literal

from langgraph.types import Command

from orchestrator_agent.deps import DepsProvider
from orchestrator_agent.planning.policies import enforce_policies
from orchestrator_agent.planning.validate import validate_plan
from orchestrator_agent.state import OrchestratorState
from utils import Plan, StepStatus
from utils.events import emit, now_iso


def make_plan_guard(get_deps: DepsProvider):
    def plan_guard(state: OrchestratorState) -> Command[Literal["progress", "supervisor", "respond"]]:
        deps = get_deps()
        cards = deps.registry.cards()
        plan = Plan.model_validate(state["plan"])

        errors = validate_plan(plan, cards, deps.policies)
        if errors:
            replans = state.get("replans", 0)
            if replans >= deps.policies.max_replans:
                return Command(goto="respond", update={
                    "final": "I could not build a valid plan for this request:\n- " + "\n- ".join(errors)})
            return Command(goto="supervisor", update={"feedback": errors, "replans": replans + 1})

        plan = enforce_policies(plan, cards, deps.policies)
        results = state.get("results", {})
        queued = {
            s.id: StepStatus(status="queued", agent=s.agent, updated_at=now_iso()).model_dump()
            for s in plan.steps if s.id not in results
        }
        emit("plan", plan=plan.model_dump())
        return Command(goto="progress", update={"plan": plan.model_dump(), "step_status": queued})

    return plan_guard
