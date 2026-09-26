"""communication graph:  draft -> approve (interrupt) -> send"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from communication_agent.nodes.approve import approve
from communication_agent.nodes.draft import draft
from communication_agent.nodes.send import send
from communication_agent.state import State
from utils import AgentInput, AgentOutput, RequestContext


def build_graph():
    builder = StateGraph(State, input_schema=AgentInput, output_schema=AgentOutput, context_schema=RequestContext)
    builder.add_node("draft", draft)
    builder.add_node("approve", approve)
    builder.add_node("send", send, retry_policy=RetryPolicy(max_attempts=3))

    builder.add_edge(START, "draft")
    builder.add_edge("draft", "approve")
    # approve -> send | END is decided by Command inside `approve`
    builder.add_edge("send", END)
    return builder.compile(name="communication")


graph = build_graph()
