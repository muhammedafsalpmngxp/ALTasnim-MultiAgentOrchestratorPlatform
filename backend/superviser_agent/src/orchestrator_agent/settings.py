"""Loads config/agents.<env>.yaml and config/policies.yaml."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

PACKAGE_ROOT = Path(__file__).resolve().parents[2]  # backend/superviser_agent


class Policies(BaseModel):
    """The supervisor's limits and rules (config/policies.yaml; an admin can change them at runtime).

    The limits (max_replans, max_clarifications, max_plan_repairs) end the loops. verify_final is
    the platform's check (planning/checks.py). max_steps and allowed_email_domains are kept for the admin console
    and are not enforced yet.
    """

    max_replans: int = Field(2, ge=0, le=10)
    max_clarifications: int = Field(2, ge=0, le=10)
    # How often the supervisor's LLM may fix a plan that cannot run (unknown step in depends_on, a cycle, ...).
    max_plan_repairs: int = Field(2, ge=0, le=5)
    max_steps: int = Field(10, ge=1, le=50)
    verify_final: bool = True  # check that every final answer matches the user's question
    # not used (the final answer is checked instead); kept so saved policies and the admin console still load
    verify_before_approval: bool = True
    verify_before_synthesis: bool = True
    allowed_email_domains: list[str] = Field(default_factory=list)


class AgentConfig(BaseModel):
    enabled: bool = True
    # Every agent is a LangGraph deployment: the port it listens on and its graph (runs via /threads/{id}/runs).
    # The machine is found on the network (discovery.py). Env AGENT_<NAME>=PORT overrides the port.
    port: int | None = None
    graph_id: str | None = None
    # A fixed base URL instead (e.g. http://localhost:8201): skips the network search. Env AGENT_<NAME>_URL.
    url: str | None = None
    # Card fields the supervisor plans with, merged over the agent's GET /card (for agents whose card lacks them)
    card: dict[str, Any] | None = None
    local_graph: str | None = None
    local_card: str | None = None


class AgentsConfig(BaseModel):
    transport: str = "local"
    # Networks searched for the agents' machines, e.g. "192.168.1.0/24"; empty = this machine's own /24
    subnet: str = ""
    agents: dict[str, AgentConfig] = Field(default_factory=dict)


def _resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else PACKAGE_ROOT / p


# backend/.env overrides of the loop limits (the yaml values are the defaults)
ENV_LIMITS = {
    "max_replans": "SUPERVISOR_MAX_REPLANS",
    "max_plan_repairs": "SUPERVISOR_MAX_PLAN_REPAIRS",
    "max_clarifications": "SUPERVISOR_MAX_CLARIFICATIONS",
}


def load_policies(path: str | None = None) -> Policies:
    file = _resolve(path or os.getenv("POLICIES_CONFIG", "config/policies.yaml"))
    data = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
    for field, env in ENV_LIMITS.items():
        if value := os.getenv(env, "").strip():
            if not value.isdigit():  # fail at startup on a typo, not in the middle of a run
                raise ValueError(f"{env}={value!r} must be a whole number, e.g. 2")
            data[field] = int(value)
    return Policies.model_validate(data)  # out-of-range values (e.g. 99) fail here with the allowed range


def load_agents_config(path: str | None = None) -> AgentsConfig:
    file = _resolve(path or os.getenv("AGENTS_CONFIG", "config/agents.dev.yaml"))
    cfg = AgentsConfig.model_validate(yaml.safe_load(file.read_text(encoding="utf-8")) or {})
    if os.getenv("AGENT_TRANSPORT"):
        cfg.transport = os.environ["AGENT_TRANSPORT"]
    cfg.subnet = os.getenv("AGENT_SUBNET", cfg.subnet)
    # backend/.env (supervisor OUTPUT): AGENT_<NAME>=PORT overrides the yaml port, AGENT_<NAME>_URL the url.
    for name, agent in cfg.agents.items():
        if port := os.getenv(f"AGENT_{name.upper()}", "").strip():
            if not port.isdigit():  # fail at startup on a typo, not on the first request
                raise ValueError(f"AGENT_{name.upper()}={port!r} must be the agent's port, e.g. 8201")
            agent.port = int(port)
        if url := os.getenv(f"AGENT_{name.upper()}_URL", "").strip():
            agent.url = url
    return cfg
