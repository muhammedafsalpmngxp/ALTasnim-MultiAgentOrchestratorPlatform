"""Custom platform routes on the orchestrator deployment (langgraph.json -> http.app).

Runs, threads, streaming, approvals and crons use the built-in Agent Server API.
Only platform-specific views live here: the agents the supervisor plans with, its policies, and the admin view
of every agent (port, graph, machine, status, card) with re-check, pause / resume and its planning text (customised
and saved to a file, registry/overrides.py), the policies (changed at runtime: they apply at once, until reset or
a restart) and the audit log of every admin action.
No auth on these routes while AUTH_MODE=dev: keep the supervisor's port on the internal network.
"""

from __future__ import annotations

import os
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException

from orchestrator_agent.deps import default_deps
from orchestrator_agent.llm import model_name
from orchestrator_agent.registry import AgentRegistry, overrides
from orchestrator_agent.registry.overrides import FIELDS, PlanningText
from orchestrator_agent.settings import Policies, load_agents_config, load_policies

app = FastAPI(title="orchestrator platform routes")

_AUDIT: deque[dict] = deque(maxlen=200)  # newest first; in memory (the supervisor's lifetime)


def _audit(action: str, target: str, detail: str = "") -> None:
    _AUDIT.appendleft({"at": datetime.now(UTC).isoformat(), "action": action, "target": target, "detail": detail,
                       "by": "developer (AUTH_MODE=dev)"})


_NOT_A_NODE = {"status": "disabled", "reachable": False, "paused": False, "url": None, "latency_ms": None,
               "checked_at": None, "error": None, "card": None, "overrides": {}, "planning_defaults": None}


@app.get("/platform/agents")
def agents() -> dict:
    """Agents the supervisor can currently plan with (healthy, enabled, not paused)."""
    return {name: card.model_dump() for name, card in default_deps().registry.cards().items()}


@app.get("/platform/policies")
def policies() -> dict:
    return default_deps().policies.model_dump()


@app.get("/platform/admin/agents")
def admin_agents() -> dict:
    """Every agent of config/agents.*.yaml: whether it is a node, its port and graph, the machine it was found
    on, status (up | down | not_found | paused | in_process | disabled), card latency, last check, error, card."""
    registry = default_deps().registry
    registry.cards()  # checks the agents (each at most every 60 s; the first check may search the network)
    config = load_agents_config()
    nodes = set(registry.names())
    rows = []
    for name, agent in config.agents.items():
        row = {"name": name, "node": name in nodes, "port": agent.port, "graph_id": agent.graph_id,
               "pinned_url": agent.url}
        rows.append({**row, **(registry.status(name) if name in nodes else _NOT_A_NODE)})
    supervisor = {"port": int(os.getenv("ORCHESTRATOR_PORT", "8100")), "graph_id": "orchestrator",
                  "llm_model": model_name()}  # SUPERVISOR_LLM_MODEL; None: the supervisor cannot plan
    return {"supervisor": supervisor,
            "transport": config.transport, "subnet": config.subnet or None, "agents": rows}


def _act(name: str, verb: str, action: Callable[[AgentRegistry], None]) -> dict:
    registry = default_deps().registry
    try:
        action(registry)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0])) from None
    status = registry.status(name)
    _audit(f"agent.{verb}", name, f"status: {status['status']}" + (f" at {status['url']}" if status["url"] else ""))
    return {"name": name, **status}


@app.post("/platform/admin/agents/{name}/recheck")
def recheck_agent(name: str) -> dict:
    """Search the network for the agent again and fetch its card now."""
    return _act(name, "recheck", lambda registry: registry.recheck(name))


@app.post("/platform/admin/agents/{name}/pause")
def pause_agent(name: str) -> dict:
    """Leave the agent out of planning (it stays a node; until resumed or the supervisor restarts)."""
    return _act(name, "pause", lambda registry: registry.set_paused(name, True))


@app.post("/platform/admin/agents/{name}/resume")
def resume_agent(name: str) -> dict:
    return _act(name, "resume", lambda registry: registry.set_paused(name, False))


def _customise(name: str, fields: dict, action: str) -> dict:
    registry = default_deps().registry
    try:
        before = registry.status(name)["overrides"]
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0])) from None
    after = registry.customise(name, fields)
    overrides.save(name, after)
    own = "the agent's own"
    changed = [f"{f}: {'customised' if f in after else own}" for f in FIELDS if before.get(f) != after.get(f)]
    _audit(action, name, "; ".join(changed) or "no change")
    return {"name": name, **registry.status(name)}


@app.put("/platform/admin/agents/{name}/planning")
def customise_agent(name: str, text: PlanningText) -> dict:
    """Customise what the supervisor reads when it chooses agents: description, when to use / not to use, examples
    (a field left out is the agent's own). Saved to AGENT_OVERRIDES_FILE; used from the next question."""
    return _customise(name, text.model_dump(exclude_none=True), "agent.customise")


@app.delete("/platform/admin/agents/{name}/planning")
def reset_agent_planning(name: str) -> dict:
    """Back to the agent's own card."""
    return _customise(name, {}, "agent.reset_planning")


@app.put("/platform/admin/policies")
def update_policies(policies: Policies) -> dict:
    """Replace the policies now (validated; 422 if out of range). Every new step uses them; until reset or restart."""
    deps = default_deps()
    before, after = deps.policies.model_dump(), policies.model_dump()
    changed = [f"{key}: {before.get(key)!r} -> {value!r}" for key, value in after.items() if before.get(key) != value]
    deps.policies = policies
    _audit("policies.update", "policies", "; ".join(changed) or "no change")
    return after


@app.post("/platform/admin/policies/reset")
def reset_policies() -> dict:
    """Back to config/policies.yaml."""
    deps = default_deps()
    deps.policies = load_policies()
    _audit("policies.reset", "policies", "reloaded config/policies.yaml")
    return deps.policies.model_dump()


@app.get("/platform/admin/audit")
def audit_log() -> list[dict]:
    """Every admin action of this supervisor's lifetime, newest first (at most 200)."""
    return list(_AUDIT)
