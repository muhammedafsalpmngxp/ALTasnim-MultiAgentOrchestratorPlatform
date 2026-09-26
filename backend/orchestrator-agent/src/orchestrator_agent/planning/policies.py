"""Policy steps inserted by code, never trusted to the LLM.

1. Before any step that needs human approval (approval_mode internal/gate),
   insert a verifier on that step's inputs, so the approver sees checked data.
2. approval_mode "gate": insert an orchestrator ``hitl`` step before the agent.
3. If the plan has no verifier at all, verify the final steps.
4. Approvals run one at a time (one open interrupt per run keeps the inbox simple).

Policy steps use ``after`` (ordering only), so they never change which data a
supervisor step receives.
"""

from __future__ import annotations

from orchestrator_agent.settings import Policies
from utils import AgentCard, Plan, Step


def _needs_approval(step: Step, cards: dict[str, AgentCard]) -> bool:
    if step.kind == "hitl":
        return True
    card = cards.get(step.agent)
    return card is not None and card.approval_mode in ("internal", "gate")


def enforce_policies(plan: Plan, cards: dict[str, AgentCard], policies: Policies) -> Plan:
    has_verifier = "verifier" in cards
    out: list[Step] = []

    for step in plan.steps:
        step = step.model_copy(deep=True)
        card = cards.get(step.agent)
        mode = card.approval_mode if card else "none"

        if step.kind == "agent" and mode in ("internal", "gate"):
            if policies.verify_before_approval and has_verifier and step.depends_on:
                verify = Step(id=f"v_{step.id}", agent="verifier", added_by="policy",
                              objective=f"Verify inputs before: {step.objective}",
                              depends_on=list(step.depends_on), after=list(step.after))
                out.append(verify)
                step.after = [*step.after, verify.id]
            if mode == "gate":
                gate = Step(id=f"g_{step.id}", agent="hitl", kind="hitl", added_by="policy",
                            objective=f"Approve: {step.objective}",
                            depends_on=list(step.depends_on), after=list(step.after))
                out.append(gate)
                step.after = [*step.after, gate.id]
        out.append(step)

    if policies.verify_final and has_verifier and not any(s.agent == "verifier" for s in out):
        depended = {d for s in out for d in (*s.depends_on, *s.after)}
        leaves = [s.id for s in out if s.id not in depended and s.kind == "agent"]
        if leaves:
            out.append(Step(id="v_final", agent="verifier", added_by="policy",
                            objective="Verify the results answer the user's request", depends_on=leaves))

    # One approval at a time: each approval step waits for the previous one.
    previous: str | None = None
    for step in out:
        if _needs_approval(step, cards):
            if previous and previous not in step.after:
                step.after.append(previous)
            previous = step.id

    return plan.model_copy(update={"steps": out})
