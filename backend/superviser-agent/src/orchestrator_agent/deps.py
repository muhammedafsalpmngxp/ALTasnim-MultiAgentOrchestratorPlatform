"""Dependencies of the orchestrator nodes (registry, supervisor, policies).

Created lazily on first use, so importing the graph (e.g. by ``langgraph dev``)
never calls other deployments. The supervisor's LLM is created on its first
decision, so the server and the admin console start without it. Tests pass
their own ``Deps`` to ``build_graph`` (e.g. a ``ScriptedSupervisor``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from orchestrator_agent.planning.llm_supervisor import LLMSupervisor, Supervisor
from orchestrator_agent.registry import AgentRegistry
from orchestrator_agent.settings import Policies, load_policies


@dataclass
class Deps:
    registry: AgentRegistry
    supervisor: Supervisor
    policies: Policies

    @classmethod
    def from_env(cls) -> Deps:
        return cls(registry=AgentRegistry.from_config(), supervisor=LLMSupervisor(), policies=load_policies())


DepsProvider = Callable[[], Deps]

_default: Deps | None = None


def default_deps() -> Deps:
    global _default
    if _default is None:
        _default = Deps.from_env()
    return _default
