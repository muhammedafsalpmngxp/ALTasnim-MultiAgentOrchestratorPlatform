"""The platform's check (code, no LLM): plan_guard adds a verifier step after every final answer, by policy.

The supervisor's LLM never plans a verifier (it is not in its catalogue); the platform adds the check itself, so it
cannot be forgotten. The verifier is found by role (``verifier`` on its card), never by name. It checks only that the
answer matches the user's question: it gets the question and the answer, nothing else.

- verify_final   after every final answer step: a ``check_<id>`` step (``added_by="policy"``) that depends on the
                 answer only. A step that uses the answer (e.g. an email of it) waits for the check.

No check when the plan already has a verifier step on the answer.
"""

from __future__ import annotations

from orchestrator_agent.planning.roles import agents_with_role
from orchestrator_agent.settings import Policies
from utils import AgentCard, Plan, Step

CHECK_PREFIX = "check_"


def _ancestors(steps: dict[str, Step], sid: str) -> list[str]:
    """Every step whose output reaches ``sid`` (through depends_on), nearest first, no duplicates."""
    seen: list[str] = []
    todo = list(steps[sid].depends_on)
    while todo:
        dep = todo.pop(0)
        if dep in steps and dep not in seen:
            seen.append(dep)
            todo += steps[dep].depends_on
    return seen


def _fit(params: dict, card: AgentCard) -> dict:
    """Only the params the verifier's schema knows, when it lists them (a third-party verifier may take fewer)."""
    props = card.params_schema.get("properties")
    if not props:
        return params
    return {k: v for k, v in params.items() if k in props}


def _new_id(base: str, taken: set[str]) -> str:
    sid, n = base, 2
    while sid in taken:
        sid, n = f"{base}_{n}", n + 1
    taken.add(sid)
    return sid


def add_checks(plan: Plan, cards: dict[str, AgentCard], policies: Policies, request: str) -> Plan:
    """The plan with the platform's check steps (unchanged when there is no verifier or no final answer)."""
    verifiers = sorted(agents_with_role(cards, "verifier"))
    if not verifiers or not policies.verify_final:
        return plan
    verifier = verifiers[0]
    steps = {s.id: s.model_copy(deep=True) for s in plan.steps}
    order = [s.id for s in plan.steps]
    taken = set(order)

    def role(sid: str) -> str | None:
        card = cards.get(steps[sid].agent)
        return card.role if card else None

    added: list[Step] = []
    checks: dict[str, str] = {}  # final step -> its check step
    for fid in [s for s in order if role(s) == "final_answer"]:
        if any(role(s) == "verifier" and fid in steps[s].depends_on for s in order):
            continue  # the plan already checks it
        cid = _new_id(f"{CHECK_PREFIX}{fid}", taken)
        added.append(Step(
            id=cid, agent=verifier, added_by="policy", depends_on=[fid],
            objective=f"Check that the answer of step {fid} matches the user's question",
            params=_fit({"request": request, "answer_step": fid}, cards[verifier]),
            expected_output="passed, or what in the question the answer does not respond to"))
        checks[fid] = cid
    if not added:
        return plan

    for sid in order:  # a step that uses a checked answer (e.g. an email of it) waits for its check
        waits = [checks[d] for d in _ancestors(steps, sid) if d in checks]
        if waits:
            steps[sid].after = list(dict.fromkeys([*steps[sid].after, *waits]))
    return plan.model_copy(update={"steps": [*(steps[s] for s in order), *added]})
