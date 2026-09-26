"""web_search graph:  plan_queries -> Send(search x N, parallel) -> summarize

Served by LangGraph Agent Server (see langgraph.json). Persistence is provided
by the server, so compile() gets no checkpointer here.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from utils import AgentInput, AgentOutput, RequestContext
from web_search_agent.nodes.plan_queries import plan_queries
from web_search_agent.nodes.search import search
from web_search_agent.nodes.summarize import summarize
from web_search_agent.routing import fan_out_searches
from web_search_agent.state import State


def build_graph():
    builder = StateGraph(State, input_schema=AgentInput, output_schema=AgentOutput, context_schema=RequestContext)
    builder.add_node("plan_queries", plan_queries, retry_policy=RetryPolicy(max_attempts=3))
    builder.add_node("search", search, retry_policy=RetryPolicy(max_attempts=3))
    builder.add_node("summarize", summarize)

    builder.add_edge(START, "plan_queries")
    builder.add_conditional_edges("plan_queries", fan_out_searches, ["search"])
    builder.add_edge("search", "summarize")
    builder.add_edge("summarize", END)
    return builder.compile(name="web_search")


graph = build_graph()
