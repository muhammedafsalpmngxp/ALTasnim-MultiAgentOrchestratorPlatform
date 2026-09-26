"""Supervisor: decides answer / clarify / plan. The plan says WHICH agents run and WHEN."""

from __future__ import annotations

from typing import Literal

from langchain_core.messages import AIMessage
from langgraph.types import Command

from orchestrator_agent.deps import DepsProvider
from orchestrator_agent.state import OrchestratorState
from utils import Plan
from utils.events import emit


def make_supervisor(get_deps: DepsProvider):
    def supervisor(state: OrchestratorState) -> Command[Literal["plan_guard", "clarify", "respond"]]:
        deps = get_deps()
        cards = deps.registry.cards()
        results = state.get("results", {})
        done = {k: v["output"] for k, v in results.items() if v.get("status") == "ok"}
        clarifications = state.get("clarifications", [])

        decision = deps.planner.decide(state["request"], clarifications, cards, done, state.get("feedback", []))
        emit("supervisor_decision", action=decision.action, reasoning=decision.reasoning)

        if decision.action == "clarify" and len(clarifications) >= deps.policies.max_clarifications:
            decision = decision.model_copy(update={
                "action": "answer",
                "answer": f"I still need more details to continue: {decision.question}",
            })

        if decision.action == "answer" or (decision.action == "plan" and decision.plan is None):
            return Command(goto="respond", update={"final": decision.answer or "I could not plan this request."})

        if decision.action == "clarify":
            question = decision.question or "Could you give more details?"
            return Command(goto="clarify",
                           update={"pending_question": question, "messages": [AIMessage(question)]})

        previous = state.get("plan")
        plan: Plan = decision.plan
        if previous:
            plan = plan.model_copy(update={"plan_id": previous["plan_id"], "version": previous["version"] + 1})
        return Command(goto="plan_guard", update={"plan": plan.model_dump()})

    return supervisor
