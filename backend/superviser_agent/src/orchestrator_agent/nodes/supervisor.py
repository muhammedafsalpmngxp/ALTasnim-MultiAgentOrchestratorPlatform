"""Supervisor: its LLM decides what happens (planning/llm_supervisor.py). The plan says WHICH agents run and WHEN.

plan mode   (no plan yet: a new request, or after a clarification)  -> answer | clarify | plan
review mode (progress calls it again: a step failed, the platform's check rejected the result, or the run
             ended without a final answer)                          -> finish | plan (revised) | clarify | answer

The limits are code: max_clarifications, max_replans (revised plans per request). A revised plan keeps the
plan's id (version + 1) and the results of the steps it keeps unchanged.
"""

from __future__ import annotations

import logging
from typing import Literal

from langchain_core.messages import AIMessage
from langgraph.types import Command

from orchestrator_agent.deps import DepsProvider
from orchestrator_agent.llm import SupervisorLLMUnavailable
from orchestrator_agent.planning.llm_supervisor import HISTORY_MESSAGES, PlanNotRunnable, SupervisorContext
from orchestrator_agent.planning.roles import agents_with_role
from orchestrator_agent.state import OrchestratorState
from utils import Plan, Step
from utils.events import emit

log = logging.getLogger(__name__)


def _reply(text: str) -> Command:
    return Command(goto="respond", update={"final": text})


def history(state: OrchestratorState) -> list[tuple[str, str]]:
    """The chat before this request: (user | assistant, text), oldest first."""
    messages = state.get("messages", [])
    request = state.get("request", "")
    start = next((i for i in range(len(messages) - 1, -1, -1)
                  if messages[i].type == "human" and messages[i].content == request), len(messages))
    earlier = [m for m in messages[:start]
               if m.type in ("human", "ai") and isinstance(m.content, str) and m.content.strip()]
    return [("user" if m.type == "human" else "assistant", m.content) for m in earlier[-HISTORY_MESSAGES:]]


def _same(a: Step, b: Step) -> bool:
    return (a.agent, a.objective, a.params, sorted(a.depends_on)) == (b.agent, b.objective, b.params,
                                                                      sorted(b.depends_on))


def reusable(new: Plan, old: Plan | None, results: dict) -> set[str]:
    """Steps of the revised plan whose results are kept: unchanged, finished ok, and every step they depend on
    is kept too (a step whose inputs change runs again)."""
    if old is None:
        return set()
    old_steps = {s.id: s for s in old.steps}
    new_steps = {s.id: s for s in new.steps}
    keep = {sid for sid, s in new_steps.items()
            if sid in old_steps and results.get(sid, {}).get("status") == "ok" and _same(s, old_steps[sid])}
    changed = True
    while changed:
        changed = False
        for sid in list(keep):
            if not set(new_steps[sid].depends_on) <= keep:
                keep.discard(sid)
                changed = True
    return keep


def make_supervisor(get_deps: DepsProvider):
    def supervisor(state: OrchestratorState) -> Command[Literal["plan_guard", "clarify", "respond"]]:
        deps = get_deps()
        policies = deps.policies
        cards = deps.registry.cards()
        previous = Plan.model_validate(state["plan"]) if state.get("plan") else None
        mode = "review" if previous else "plan"
        replans = state.get("replans", 0)
        clarifications = state.get("clarifications", [])
        results = state.get("results", {})

        if not cards:
            return _reply("No agent is available right now. Please try again in a moment.")

        # The verifiers are run by the platform (plan_guard adds the checks), so the LLM never plans one.
        planning = {name: card for name, card in cards.items() if card.role != "verifier"}
        ctx = SupervisorContext(
            mode=mode, request=state["request"], cards=planning, history=history(state),
            clarifications=clarifications, plan=previous, results=results, step_status=state.get("step_status", {}),
            feedback=state.get("feedback", []), review_reason=state.get("review_reason"),
            replans_left=max(0, policies.max_replans - replans), max_repairs=policies.max_plan_repairs,
        )
        emit("supervisor_thinking", mode=mode)
        try:
            decision = deps.supervisor.decide(ctx)
        except SupervisorLLMUnavailable as exc:
            log.error("supervisor LLM unavailable: %s", exc)
            return _reply(f"{exc} Please contact the platform admin.")
        except PlanNotRunnable as exc:
            return _reply("I could not build a valid plan for this request:\n- " + "\n- ".join(exc.errors))
        except Exception as exc:  # noqa: BLE001 - API error, timeout, rate limit: a clear reply, not a crashed run
            log.exception("supervisor LLM failed")
            return _reply(f"The supervisor's LLM failed ({type(exc).__name__}: {exc}). Please try again.")

        emit("supervisor_decision", mode=mode, action=decision.action, understanding=decision.understanding,
             needs=decision.needs, reasoning=decision.reasoning, usage=ctx.usage)

        if decision.action == "clarify":
            if len(clarifications) >= policies.max_clarifications:
                return _reply(f"I still need more details to continue: {decision.question}")
            return Command(goto="clarify", update={"pending_question": decision.question,
                                                   "messages": [AIMessage(decision.question)]})

        if decision.action == "plan":
            if mode == "review" and replans >= policies.max_replans:
                reasons = state.get("feedback") or [decision.reasoning or "no more replans left"]
                return _reply("I could not complete the request:\n- " + "\n- ".join(reasons))
            plan = decision.plan
            if previous:
                plan = plan.model_copy(update={"plan_id": previous.plan_id, "version": previous.version + 1})
            keep = reusable(plan, previous, results)
            return Command(goto="plan_guard", update={
                "plan": plan.model_dump(),
                "results": {k: None for k in results if k not in keep},
                "step_status": {k: None for k in state.get("step_status", {}) if k not in keep},
                "replans": replans + (1 if mode == "review" else 0),
                "review_reason": None,
            })

        if decision.action == "finish" and previous:
            final_steps = {s.id for s in previous.steps if s.agent in agents_with_role(cards, "final_answer")}
            answered = any(results.get(sid, {}).get("status") == "ok" for sid in final_steps)
            # the final_answer agent wrote the reply (respond takes it); else the supervisor's own answer
            return Command(goto="respond", update={"final": None if answered else decision.answer})

        return _reply(decision.answer or "I could not answer this request.")

    return supervisor
