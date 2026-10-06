"""The supervisor's thinking: its LLM decides what happens for a request (structured output).

plan mode   (a new request)                    -> answer | clarify | plan
review mode (a step failed, a verifier rejected data, or the run ended without a final answer)
                                               -> finish | plan (revised) | clarify | answer

The LLM sees the request, the chat history and the AGENT CATALOGUE rendered from the agents' cards (role,
description, when to use / not to use, examples, params schema, returns). Nothing about a specific agent is
written here or in the prompts, so a new agent is planned from its card alone.

The output schema is built per call: ``agent`` can only be one of the agents available right now. A plan that
cannot run (unknown step in depends_on, a cycle, ...) goes back to the LLM with the errors, at most
``max_repairs`` times.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Literal, Protocol

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field, create_model

from orchestrator_agent.llm import supervisor_model
from orchestrator_agent.planning.validate import check_plan
from utils import AgentCard, Plan, Step, SupervisorDecision

log = logging.getLogger(__name__)

PROMPTS = Path(__file__).parent.parent / "prompts"
PLAN_PROMPT = (PROMPTS / "supervisor_plan.md").read_text(encoding="utf-8")
REVIEW_PROMPT = (PROMPTS / "supervisor_review.md").read_text(encoding="utf-8")

STEP_DIGEST_CHARS = 1500  # of each step's result shown to the LLM
HISTORY_MESSAGES = 6
HISTORY_CHARS = 600

Mode = Literal["plan", "review"]


class PlanNotRunnable(RuntimeError):
    """The LLM's plan still cannot run after the repairs."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass
class SupervisorContext:
    """Everything the supervisor decides from."""

    mode: Mode
    request: str
    cards: dict[str, AgentCard]
    history: list[tuple[str, str]] = field(default_factory=list)  # (user | assistant, text), oldest first
    clarifications: list[str] = field(default_factory=list)
    plan: Plan | None = None
    results: dict[str, dict] = field(default_factory=dict)
    step_status: dict[str, dict] = field(default_factory=dict)
    feedback: list[str] = field(default_factory=list)
    review_reason: str | None = None  # failed | complete
    replans_left: int = 0
    max_repairs: int = 2
    today: str = field(default_factory=lambda: date.today().isoformat())
    usage: dict[str, int] = field(default_factory=dict)  # tokens used by this decision (filled by the supervisor)


class Supervisor(Protocol):
    def decide(self, ctx: SupervisorContext) -> SupervisorDecision: ...


# --------------------------------------------------------------------------- #
# Output schema (built per call from the available agents)
# --------------------------------------------------------------------------- #

def decision_schema(agents: list[str]) -> type[BaseModel]:
    agent_type = Literal[tuple(agents)] if agents else str
    step = create_model(
        "PlanStep",
        id=(str, Field(description="Short unique id: s1, s2, s3, ...")),
        agent=(agent_type, Field(description="The agent that does this step (from the AGENT CATALOGUE).")),
        objective=(str, Field(description="One clear, self-contained instruction for the agent.")),
        params=(dict[str, Any], Field(default_factory=dict,
                                      description="Inputs for the agent, following its params schema exactly.")),
        depends_on=(list[str], Field(default_factory=list,
                                     description="Ids of the steps whose OUTPUT this step needs (runs after them).")),
        expected_output=(str, Field("", description="One line: what a good result of this step looks like.")),
    )
    plan = create_model(
        "PlanDraft",
        goal=(str, Field(description="The request as one task.")),
        reasoning=(str, Field("", description="The chosen agents and order in one or two sentences.")),
        success_criteria=(list[str], Field(default_factory=list,
                                           description="1 to 4 checkable statements of what 'done' means.")),
        steps=(list[step], Field(description="The steps, in any order; depends_on sets the order.")),
    )
    return create_model(
        "SupervisorDecision",
        __doc__="The supervisor's decision for the user's request.",
        understanding=(str, Field(description="What the user really wants, in one sentence.")),
        needs=(list[str], Field(default_factory=list, description="What is needed to fully satisfy the request.")),
        reasoning=(str, Field(description="Which agents cover each need and why, the order, what runs in parallel, "
                                          "assumptions.")),
        action=(Literal["answer", "clarify", "plan", "finish"], Field(description="What happens next.")),
        answer=(str | None, Field(None, description="The reply to the user (answer / finish).")),
        question=(str | None, Field(None, description="ONE short question to the user (clarify).")),
        plan=(plan | None, Field(None, description="The plan (plan).")),
    )


# --------------------------------------------------------------------------- #
# What the LLM reads
# --------------------------------------------------------------------------- #

def _without_titles(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _without_titles(v) for k, v in value.items() if k != "title"}
    if isinstance(value, list):
        return [_without_titles(v) for v in value]
    return value


def _compact(value: Any) -> str:
    return json.dumps(_without_titles(value), ensure_ascii=False, separators=(",", ":"))


def _cut(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit].rstrip() + " …"


def render_card(card: AgentCard) -> str:
    lines = [
        f"### {card.name}",
        f"- role: {card.role or 'not set'}",
        f"- description: {card.description}",
        f"- when to use: {card.when_to_use}",
        f"- when NOT to use: {card.when_not_to_use}",
    ]
    if card.examples:
        lines.append(f"- examples: {' | '.join(card.examples)}")
    lines.append(f"- side effects: {'yes' if card.side_effects else 'no'}; human approval: {card.approval_mode}")
    lines.append(f"- params schema: {_compact(card.params_schema)}")
    returns = card.output_schema.get("properties", {})
    if returns:
        fields = [f"{name} ({spec['description']})" if isinstance(spec, dict) and spec.get("description") else name
                  for name, spec in returns.items()]
        lines.append(f"- returns: {', '.join(fields)}")
    return "\n".join(lines)


def digest(output: dict | None, limit: int = STEP_DIGEST_CHARS) -> str:
    """A step's result as short text: its summary / answer, else the text of its findings / chunks."""
    output = output or {}
    parts: list[str] = []
    text = output.get("summary") or output.get("answer")
    if text:
        parts.append(str(text))
    else:
        for item in [*(output.get("findings") or []), *(output.get("chunks") or [])]:
            if isinstance(item, dict):
                body = item.get("content") or item.get("text") or item.get("snippet") or ""
                label = item.get("title") or item.get("document_name") or ""
                if str(body).strip():
                    parts.append(f"[{label}] {body}" if label else str(body))
    for key in ("issues", "warnings"):
        if values := output.get(key):
            parts.append(f"{key}: " + "; ".join(map(str, values)))
    if sources := output.get("sources"):
        parts.append("sources: " + ", ".join(map(str, sources[:5])))
    if not parts:
        parts.append(_compact(output) if output else "(empty)")
    return _cut("\n".join(parts), limit)


def _step_state(ctx: SupervisorContext, step_id: str) -> tuple[str, str | None]:
    result = ctx.results.get(step_id)
    if result:
        status = result.get("status", "?")
        detail = result.get("error") if status != "ok" else None
        return status, detail
    return (ctx.step_status.get(step_id) or {}).get("status", "not run"), None


def render_context(ctx: SupervisorContext) -> str:
    sections = [f"TODAY: {ctx.today}"]
    if ctx.history:
        lines = [f"{who}: {_cut(text, HISTORY_CHARS)}" for who, text in ctx.history]
        sections.append("CONVERSATION SO FAR (oldest first)\n" + "\n".join(lines))
    sections.append("USER REQUEST\n" + ctx.request)
    if ctx.clarifications:
        sections.append("THE USER'S ANSWERS TO YOUR QUESTIONS\n" + "\n".join(f"- {c}" for c in ctx.clarifications))
    catalogue = "\n\n".join(render_card(card) for card in ctx.cards.values()) or "(no agent is available)"
    sections.append("AGENT CATALOGUE\n\n" + catalogue)

    if ctx.mode == "review":
        if ctx.review_reason == "complete":
            why = ("All steps finished, but no final_answer step wrote the reply. Check the results against the "
                   "success criteria: finish (write the reply from the results) or plan the missing work.")
        else:
            why = "A step failed or a verifier rejected data:\n" + "\n".join(f"- {f}" for f in ctx.feedback)
        sections.append("WHY YOU ARE REVIEWING\n" + why)
        if ctx.plan:
            lines = [f"goal: {ctx.plan.goal}",
                     "success criteria: " + ("; ".join(ctx.plan.success_criteria) or "(none)"), ""]
            for step in ctx.plan.steps:
                status, detail = _step_state(ctx, step.id)
                lines.append(f"- {step.id} · agent {step.agent} · status: {status}")
                lines.append(f"  objective: {step.objective}")
                if step.params:
                    lines.append(f"  params: {_compact(step.params)}")
                if step.depends_on:
                    lines.append(f"  depends_on: {', '.join(step.depends_on)}")
                if detail:
                    lines.append(f"  error: {_cut(str(detail), 400)}")
                if step.id in ctx.results:
                    lines.append("  result: " + digest(ctx.results[step.id].get("output")).replace("\n", "\n  "))
            sections.append(f"CURRENT PLAN AND RESULTS (plan version {ctx.plan.version})\n" + "\n".join(lines))
        left = f"REPLANS LEFT: {ctx.replans_left}"
        if ctx.replans_left <= 0:
            left += " (you cannot make a new plan: finish or answer)"
        sections.append(left)
    return "\n\n".join(sections)


# --------------------------------------------------------------------------- #
# The decision
# --------------------------------------------------------------------------- #

def to_decision(parsed: BaseModel, ctx: SupervisorContext) -> tuple[SupervisorDecision, list[str]]:
    """The LLM's output as a SupervisorDecision, and why it cannot be used (empty: it can)."""
    data = parsed.model_dump()
    plan = None
    errors: list[str] = []
    if data["action"] == "plan":
        draft = data.get("plan")
        if not draft or not draft.get("steps"):
            errors.append("action is 'plan' but the plan has no steps")
        else:
            steps = [Step(id=s["id"], agent=s["agent"], objective=s["objective"], params=s.get("params") or {},
                          depends_on=list(dict.fromkeys(s.get("depends_on") or [])),
                          expected_output=s.get("expected_output") or "")
                     for s in draft["steps"]]
            plan = Plan(goal=draft.get("goal") or ctx.request, reasoning=draft.get("reasoning") or data["reasoning"],
                        success_criteria=draft.get("success_criteria") or [], steps=steps)
            errors.extend(check_plan(plan, ctx.cards))
    if data["action"] == "clarify" and not data.get("question"):
        errors.append("action is 'clarify' but there is no question")
    decision = SupervisorDecision(action=data["action"], understanding=data.get("understanding") or "",
                                  needs=data.get("needs") or [], reasoning=data.get("reasoning") or "",
                                  answer=data.get("answer"), question=data.get("question"), plan=plan)
    return decision, errors


def _add_usage(total: dict[str, int], raw: Any) -> None:
    for key, value in (getattr(raw, "usage_metadata", None) or {}).items():
        if isinstance(value, int):
            total[key] = total.get(key, 0) + value


class LLMSupervisor:
    """``model``: for tests; by default the model of SUPERVISOR_LLM_MODEL, created on the first decision."""

    def __init__(self, model=None):
        self._model = model

    def decide(self, ctx: SupervisorContext) -> SupervisorDecision:
        model = self._model or supervisor_model()
        llm = model.with_structured_output(decision_schema(sorted(ctx.cards)), method="function_calling",
                                           include_raw=True)
        messages = [SystemMessage(PLAN_PROMPT if ctx.mode == "plan" else REVIEW_PROMPT),
                    HumanMessage(render_context(ctx))]
        errors: list[str] = []
        for attempt in range(ctx.max_repairs + 1):
            out = llm.invoke(messages)
            _add_usage(ctx.usage, out.get("raw"))
            parsed = out.get("parsed")
            if parsed is None:
                error = out.get("parsing_error") or "no decision was returned"
                errors, previous = [f"your output could not be read: {error}"], str(getattr(out.get("raw"),
                                                                                               "content", ""))
            else:
                decision, errors = to_decision(parsed, ctx)
                if not errors:
                    log.info("supervisor %s: %s (%s)", ctx.mode, decision.action, decision.reasoning)
                    return decision
                previous = parsed.model_dump_json()
            log.warning("supervisor %s: unusable decision (attempt %d): %s", ctx.mode, attempt + 1, errors)
            messages += [AIMessage(previous or "(no output)"),
                         HumanMessage("Your decision cannot be used:\n- " + "\n- ".join(errors)
                                      + "\nThink again and return the whole corrected decision.")]
        raise PlanNotRunnable(errors)
