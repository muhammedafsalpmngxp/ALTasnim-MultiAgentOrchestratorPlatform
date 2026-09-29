"""Deterministic plan validation. Errors go back to the supervisor as feedback."""

from __future__ import annotations

from jsonschema import Draft202012Validator

from orchestrator_agent.settings import Policies
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


def validate_plan(plan: Plan, cards: dict[str, AgentCard], policies: Policies) -> list[str]:
    errors: list[str] = []
    if not plan.steps:
        return ["plan has no steps"]
    if len(plan.steps) > policies.max_steps:
        errors.append(f"plan has {len(plan.steps)} steps, maximum is {policies.max_steps}")

    ids = [s.id for s in plan.steps]
    if dupes := sorted({i for i in ids if ids.count(i) > 1}):
        errors.append(f"duplicate step ids: {dupes}")

    for step in plan.steps:
        for dep in [*step.depends_on, *step.after]:
            if dep not in ids:
                errors.append(f"step {step.id}: depends on unknown step {dep!r}")
        if step.kind == "hitl":
            continue
        card = cards.get(step.agent)
        if card is None:
            errors.append(f"step {step.id}: unknown or unavailable agent {step.agent!r}; available: {sorted(cards)}")
            continue
        for err in Draft202012Validator(card.params_schema).iter_errors(step.params):
            where = ".".join(str(p) for p in err.path) or "params"
            errors.append(f"step {step.id} ({step.agent}): {where}: {err.message}")
        if step.agent == "communication" and policies.allowed_email_domains:
            for addr in step.params.get("to", []):
                domain = str(addr).rsplit("@", 1)[-1].lower()
                if domain not in policies.allowed_email_domains:
                    errors.append(f"step {step.id}: recipient {addr} is outside allowed domains")

    if cycle := _find_cycle(plan):
        errors.append(f"dependency cycle: {' -> '.join(cycle)}")
    return errors
