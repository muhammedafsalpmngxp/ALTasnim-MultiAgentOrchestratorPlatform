r"""Orchestrator root graph.

    START -> intake -> supervisor --answer--------------------------> respond -> END
                          |  ^  \--clarify--> clarify (interrupt) --^
                          |  |
                        plan |replan
                          v  |
                      plan_guard --> progress --Send--> run_agent (x N, parallel) --+
                                        ^  \----Send--> hitl_gate (interrupt) ------+
                                        +-------------------------------------------+

The graph is fixed (8 nodes). Which agents run, and when, comes from the plan JSON
the supervisor creates for each request.
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
from orchestrator_agent.state import OrchestratorInput, OrchestratorState
from utils import RequestContext


def build_graph(deps: Deps | None = None, checkpointer=None):
    """``deps``/``checkpointer`` are for tests. On Agent Server, persistence is provided by the server."""
    get_deps = (lambda: deps) if deps is not None else default_deps

    builder = StateGraph(OrchestratorState, input_schema=OrchestratorInput, context_schema=RequestContext)
    builder.add_node("intake", intake)
    builder.add_node("supervisor", make_supervisor(get_deps), retry_policy=RetryPolicy(max_attempts=3),
                     destinations=("plan_guard", "clarify", "respond"))
    builder.add_node("clarify", clarify)
    builder.add_node("plan_guard", make_plan_guard(get_deps), destinations=("progress", "supervisor", "respond"))
    builder.add_node("progress", make_progress(get_deps),
                     destinations=("run_agent", "hitl_gate", "supervisor", "respond"))
    builder.add_node("run_agent", make_run_agent(get_deps))
    builder.add_node("hitl_gate", hitl_gate)
    builder.add_node("respond", respond)

    builder.add_edge(START, "intake")
    builder.add_edge("intake", "supervisor")
    builder.add_edge("clarify", "supervisor")
    builder.add_edge("run_agent", "progress")  # after each wave, progress runs once
    builder.add_edge("hitl_gate", "progress")
    builder.add_edge("respond", END)
    return builder.compile(name="orchestrator", checkpointer=checkpointer)


graph = build_graph()
