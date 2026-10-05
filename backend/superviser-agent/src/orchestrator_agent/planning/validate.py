"""Can the plan run? (code, no LLM). The errors go back to the supervisor's LLM to fix its plan.

Only what the executor needs: steps, known agents, known dependencies, no cycle. Supervisor v1 has no guardrails
(params rules, step limits, email allowlist): they come back in v2.
"""

from __future__ import annotations

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
        if step.kind == "agent" and step.agent not in cards:
            errors.append(f"step {step.id}: unknown or unavailable agent {step.agent!r}; available: {sorted(cards)}")
    if cycle := _find_cycle(plan):
        errors.append(f"dependency cycle: {' -> '.join(cycle)}")
    return errors
