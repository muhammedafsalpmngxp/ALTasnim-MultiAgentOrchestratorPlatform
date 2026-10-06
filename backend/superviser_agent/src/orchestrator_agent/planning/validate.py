"""Can the plan run? (code, no LLM). The errors go back to the supervisor's LLM to fix its plan.

What the executor needs: steps, known agents, known dependencies, no cycle; each agent's params as its card's
params_schema says; and a step whose role works on earlier outputs (verifier, final_answer) has some.
No guardrails (step limits, email allowlist): they come back in v2.
"""

from __future__ import annotations

from jsonschema import Draft202012Validator

from utils import AgentCard, Plan


def _find_cycle(plan: Plan) -> list[str] | None:
    graph = {s.id: [*s.depends_on, *s.after] for s in plan.steps}
    visiting, done = set(), set()

    def visit(node: str, path: list[str]) -> list[str] | None:
        if node in visiting:
            return [*path, node]
        if node in done or node not in graph:
            return None
        visiting.add(node)
        for dep in graph[node]:
            if cycle := visit(dep, [*path, node]):
                return cycle
        visiting.discard(node)
        done.add(node)
        return None

    for step_id in graph:
        if cycle := visit(step_id, []):
            return cycle
    return None


# Roles that only work on the outputs of earlier steps: such a step without depends_on has nothing to work on.
NEEDS_INPUTS = {
    "verifier": "a verifier checks the outputs of earlier steps: give it depends_on (the steps it checks), or leave "
                "it out when nothing was found by another step (e.g. text the user wrote needs no verification)",
    "final_answer": "a final answer is written from the outputs of earlier steps: give it depends_on, or leave it "
                    "out when no step finds information",
}


def _param_errors(step_id: str, agent: str, params: dict, schema: dict) -> list[str]:
    """The step's params against the agent's params_schema (from its card)."""
    errors = []
    for err in Draft202012Validator(schema).iter_errors(params):
        where = ".".join(str(p) for p in err.path) or "params"
        errors.append(f"step {step_id} ({agent}): {where}: {err.message}")
    return errors


def check_plan(plan: Plan, cards: dict[str, AgentCard]) -> list[str]:
    """Why the plan cannot run (empty list: it can)."""
    if not plan.steps:
        return ["the plan has no steps"]
    errors: list[str] = []
    ids = [s.id for s in plan.steps]
    if dupes := sorted({i for i in ids if ids.count(i) > 1}):
        errors.append(f"duplicate step ids: {dupes}")
    for step in plan.steps:
        for dep in [*step.depends_on, *step.after]:
            if dep not in ids:
                errors.append(f"step {step.id}: depends on unknown step {dep!r}")
        if step.kind != "agent":
            continue
        card = cards.get(step.agent)
        if card is None:
            errors.append(f"step {step.id}: unknown or unavailable agent {step.agent!r}; available: {sorted(cards)}")
            continue
        if card.role in NEEDS_INPUTS and not step.depends_on:
            errors.append(f"step {step.id} ({step.agent}): {NEEDS_INPUTS[card.role]}")
        errors.extend(_param_errors(step.id, step.agent, step.params, card.params_schema))
    if cycle := _find_cycle(plan):
        errors.append(f"dependency cycle: {' -> '.join(cycle)}")
    return errors
