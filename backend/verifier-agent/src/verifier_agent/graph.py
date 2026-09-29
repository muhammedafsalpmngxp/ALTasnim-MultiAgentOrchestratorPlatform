"""verifier graph:  (check_evidence || check_completeness || check_answer) -> verdict"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from utils import AgentInput, AgentOutput, RequestContext
from verifier_agent.nodes.checks import check_answer, check_completeness, check_evidence, verdict
from verifier_agent.state import State


def build_graph():
    builder = StateGraph(State, input_schema=AgentInput, output_schema=AgentOutput, context_schema=RequestContext)
    builder.add_node("check_evidence", check_evidence)
    builder.add_node("check_completeness", check_completeness)
    builder.add_node("check_answer", check_answer)  # LLM: does the content answer the question?
    builder.add_node("verdict", verdict)

    for check in ("check_evidence", "check_completeness", "check_answer"):
        builder.add_edge(START, check)
    builder.add_edge(["check_evidence", "check_completeness", "check_answer"], "verdict")  # waits for all
    builder.add_edge("verdict", END)
    return builder.compile(name="verifier")


graph = build_graph()
