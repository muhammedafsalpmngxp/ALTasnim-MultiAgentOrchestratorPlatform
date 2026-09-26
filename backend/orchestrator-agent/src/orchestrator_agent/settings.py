"""Loads config/agents.<env>.yaml and config/policies.yaml."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

PACKAGE_ROOT = Path(__file__).resolve().parents[2]  # backend/orchestrator-agent


class Policies(BaseModel):
    max_steps: int = 10
    max_replans: int = 2
    max_clarifications: int = 2
    verify_before_approval: bool = True
    verify_final: bool = True
    allowed_email_domains: list[str] = Field(default_factory=list)


class AgentConfig(BaseModel):
    enabled: bool = True
    url: str | None = None
    graph_id: str | None = None
    local_graph: str | None = None
    local_card: str | None = None


class AgentsConfig(BaseModel):
    transport: str = "local"
    agents: dict[str, AgentConfig] = Field(default_factory=dict)


def _resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else PACKAGE_ROOT / p


def load_policies(path: str | None = None) -> Policies:
    file = _resolve(path or os.getenv("POLICIES_CONFIG", "config/policies.yaml"))
    return Policies.model_validate(yaml.safe_load(file.read_text(encoding="utf-8")) or {})


def load_agents_config(path: str | None = None) -> AgentsConfig:
    file = _resolve(path or os.getenv("AGENTS_CONFIG", "config/agents.dev.yaml"))
    cfg = AgentsConfig.model_validate(yaml.safe_load(file.read_text(encoding="utf-8")) or {})
    if os.getenv("AGENT_TRANSPORT"):
        cfg.transport = os.environ["AGENT_TRANSPORT"]
    # AGENT_<NAME>_URL overrides the yaml url (docker-compose uses service names).
    for name, agent in cfg.agents.items():
        if url := os.getenv(f"AGENT_{name.upper()}_URL"):
            agent.url = url
    return cfg
