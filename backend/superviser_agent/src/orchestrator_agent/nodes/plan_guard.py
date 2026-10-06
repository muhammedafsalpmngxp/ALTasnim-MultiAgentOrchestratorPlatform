"""plan_guard: adds the platform's checks to the supervisor's plan, checks that it can run (code, no LLM), then
hands it to progress.

The checks (planning/checks.py, by policy): a verifier step after every final answer, and before an action that uses
facts found by other steps. The supervisor's LLM already fixed its plan against the same run check
(planning/llm_supervisor.py); a plan that still cannot run (e.g. an agent went down meanwhile) ends the request with
the reasons.
"""

from __future__ import annotations

from typing import Literal

from langgraph.types import Command

from orchestrator_agent.deps import DepsProvider
from orchestrator_agent.planning.checks import add_checks
from orchestrator_agent.planning.validate import check_plan
from orchestrator_agent.state import OrchestratorState
from utils import Plan, StepStatus
from utils.events import emit, now_iso


def make_plan_guard(get_deps: DepsProvider):
    def plan_guard(state: OrchestratorState) -> Command[Literal["progress", "respond"]]:
        deps = get_deps()
        cards = deps.registry.cards()
        request = "\n".join([state.get("request", ""), *state.get("clarifications", [])]).strip()
        plan = add_checks(Plan.model_validate(state["plan"]), cards, deps.policies, request)
        errors = check_plan(plan, cards)
        if errors:
            return Command(goto="respond", update={
                "final": "I could not build a valid plan for this request:\n- " + "\n- ".join(errors)})

        results = state.get("results", {})
        queued = {
            s.id: StepStatus(status="queued", agent=s.agent, updated_at=now_iso()).model_dump()
            for s in plan.steps if s.id not in results
        }
        emit("plan", plan=plan.model_dump())
        return Command(goto="progress", update={"plan": plan.model_dump(), "step_status": queued})

    return plan_guard
