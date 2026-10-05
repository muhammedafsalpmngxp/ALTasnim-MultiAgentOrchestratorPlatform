"""communication graph:  draft -> approve (interrupt) -> send

draft ends the step (failed) when the params are invalid or there is nothing to send; approve ends it when the
human rejects. send retries temporary mail-server errors itself (channels/email.py), never re-sending.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from communication_agent.nodes.approve import approve
from communication_agent.nodes.draft import draft
from communication_agent.nodes.send import send
from communication_agent.state import State
from utils import AgentInput, AgentOutput, RequestContext


def build_graph():
    builder = StateGraph(State, input_schema=AgentInput, output_schema=AgentOutput, context_schema=RequestContext)
    builder.add_node("draft", draft, destinations=("approve", END))
    builder.add_node("approve", approve, destinations=("send", END))
    builder.add_node("send", send)

    builder.add_edge(START, "draft")
    # draft -> approve | END and approve -> send | END are decided by Command inside the nodes
    builder.add_edge("send", END)
    return builder.compile(name="communication")


graph = build_graph()
