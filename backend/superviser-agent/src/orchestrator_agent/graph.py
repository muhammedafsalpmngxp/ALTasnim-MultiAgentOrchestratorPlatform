r"""Supervisor (orchestrator) root graph. Every agent is a node of this graph.

    START -> intake -> supervisor --answer--------------------------> respond -> END
                          |  ^  \--clarify--> clarify (interrupt) --^
                          |  |
                        plan |replan
                          v  |
                      plan_guard --> progress --Send--> web_search    --+
                                        ^  \----Send--> communication --+   one node per agent in
                                        |   \---Send--> verifier      --+   config/agents.*.yaml;
                                        |    \--Send--> ...           --+   a wave runs in parallel
                                        |     \-Send--> hitl_gate     --+   (interrupt)
                                        +-------------------------------+

The supervisor plans which agent nodes run, and in which order (the plan JSON); progress sends each
step to its agent's node. An agent node runs the step on that agent: in-process, or on the agent's own
LangGraph deployment (transport in config/agents.*.yaml).
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from orchestrator_agent.deps import Deps, default_deps
from orchestrator_agent.nodes.clarify import clarify
from orchestrator_agent.nodes.hitl_gate import hitl_gate
from orchestrator_agent.nodes.intake import intake
from orchestrator_agent.nodes.plan_guard import make_plan_guard
from orchestrator_agent.nodes.progress import make_progress
from orchestrator_agent.nodes.respond import respond
from orchestrator_agent.nodes.run_agent import make_run_agent
from orchestrator_agent.nodes.supervisor import make_supervisor
from orchestrator_agent.settings import load_agents_config
from orchestrator_agent.state import OrchestratorInput, OrchestratorState
from utils import RequestContext

FIXED_NODES = ("intake", "supervisor", "clarify", "plan_guard", "progress", "hitl_gate", "respond")


def agent_names(deps: Deps | None = None) -> list[str]:
    """The agent nodes: the registered agents (tests), else the enabled agents of config/agents.*.yaml (read only,
    so building the graph never calls other deployments)."""
    if deps is not None:
        names = deps.registry.names()
    else:
        names = [name for name, agent in load_agents_config().agents.items() if agent.enabled]
    if clash := set(names) & set(FIXED_NODES):
        raise ValueError(f"agent names {sorted(clash)} clash with the supervisor's own nodes")
    return names


def build_graph(deps: Deps | None = None, checkpointer=None):
    """``deps``/``checkpointer`` are for tests. On Agent Server, persistence is provided by the server."""
    get_deps = (lambda: deps) if deps is not None else default_deps
    agents = agent_names(deps)

    builder = StateGraph(OrchestratorState, input_schema=OrchestratorInput, context_schema=RequestContext)
    builder.add_node("intake", intake)
    builder.add_node("supervisor", make_supervisor(get_deps), retry_policy=RetryPolicy(max_attempts=3),
                     destinations=("plan_guard", "clarify", "respond"))
    builder.add_node("clarify", clarify)
    builder.add_node("plan_guard", make_plan_guard(get_deps), destinations=("progress", "supervisor", "respond"))
    builder.add_node("progress", make_progress(get_deps),
                     destinations=(*agents, "hitl_gate", "supervisor", "respond"))
    for name in agents:  # each agent is its own node; all share the step runner (nodes/run_agent.py)
        builder.add_node(name, make_run_agent(get_deps), metadata={"agent": name})
    builder.add_node("hitl_gate", hitl_gate)
    builder.add_node("respond", respond)

    builder.add_edge(START, "intake")
    builder.add_edge("intake", "supervisor")
    builder.add_edge("clarify", "supervisor")
    for name in agents:
        builder.add_edge(name, "progress")  # after each wave, progress runs once
    builder.add_edge("hitl_gate", "progress")
    builder.add_edge("respond", END)
    return builder.compile(name="orchestrator", checkpointer=checkpointer)


graph = build_graph()
