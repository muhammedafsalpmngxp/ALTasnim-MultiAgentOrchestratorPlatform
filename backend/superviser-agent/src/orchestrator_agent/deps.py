"""Dependencies of the orchestrator nodes (registry, planner, policies).

Created lazily on first use, so importing the graph (e.g. by ``langgraph dev``)
never calls other deployments. Tests pass their own ``Deps`` to ``build_graph``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from orchestrator_agent.planning.planner import Planner, default_planner
from orchestrator_agent.registry import AgentRegistry
from orchestrator_agent.settings import Policies, load_policies


@dataclass
class Deps:
    registry: AgentRegistry
    planner: Planner
    policies: Policies

    @classmethod
    def from_env(cls) -> Deps:
        return cls(registry=AgentRegistry.from_config(), planner=default_planner(), policies=load_policies())


DepsProvider = Callable[[], Deps]

_default: Deps | None = None


def default_deps() -> Deps:
    global _default
    if _default is None:
        _default = Deps.from_env()
    return _default
