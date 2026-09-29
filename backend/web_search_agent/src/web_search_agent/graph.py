"""web_search graph: input from the supervisor (task), output (question + top 3 contents) to the verifier /
synthesizer.

    START  {"task": AgentTask}
      -> plan_queries                      read the task; fast LLM plans 1-3 queries (structured output, RetryPolicy)
      -> Send(search x N queries)          parallel
      -> select_pages                      merge + de-duplicate hits
      -> Send(extract x M pages)           parallel (-> rank for sample data, -> finalize when there are no hits)
      -> rank                              chunk + BM25/cross-encoder rerank
      -> finalize                          {"result": question + top 3 contents}
      -> send_output                       POST it to every WEB_SEARCH_VERIFIER_PATH route on the network, UI history;
                                           saves the run so "Retry" can send it again (no search, no LLM)
    END

Every node streams its step as a custom event (stream_mode="custom") for the agent UI's processing flow.
Nodes are async; ``dual()`` also makes them work with the sync ``graph.invoke`` (see dual.py).
Served by LangGraph Agent Server (see langgraph.json). Persistence is provided by the server, so compile()
gets no checkpointer here.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from utils import AgentInput, AgentOutput
from web_search_agent.context import Context
from web_search_agent.dual import dual
from web_search_agent.llm import TRANSIENT_ERRORS
from web_search_agent.nodes.extract import extract
from web_search_agent.nodes.finalize import finalize
from web_search_agent.nodes.plan_queries import plan_queries
from web_search_agent.nodes.rank import rank
from web_search_agent.nodes.search import search
from web_search_agent.nodes.select_pages import select_pages
from web_search_agent.nodes.send_output import send_output
from web_search_agent.routing import fan_out_fetch, fan_out_search
from web_search_agent.state import PageTask, SearchTask, State

LLM_RETRY = RetryPolicy(max_attempts=3, initial_interval=1.0, retry_on=TRANSIENT_ERRORS)


def build_graph():
    builder = StateGraph(State, input_schema=AgentInput, output_schema=AgentOutput, context_schema=Context)

    builder.add_node("plan_queries", dual(plan_queries), retry_policy=LLM_RETRY)
    builder.add_node("search", dual(search), input_schema=SearchTask)
    builder.add_node("select_pages", dual(select_pages))
    builder.add_node("extract", dual(extract), input_schema=PageTask)
    builder.add_node("rank", dual(rank))
    builder.add_node("finalize", dual(finalize))
    builder.add_node("send_output", dual(send_output))

    builder.add_edge(START, "plan_queries")
    builder.add_conditional_edges("plan_queries", fan_out_search, ["search"])
    builder.add_edge("search", "select_pages")
    builder.add_conditional_edges("select_pages", fan_out_fetch, ["extract", "rank", "finalize"])
    builder.add_edge("extract", "rank")
    builder.add_edge("rank", "finalize")
    builder.add_edge("finalize", "send_output")
    builder.add_edge("send_output", END)
    return builder.compile(name="web_search")


graph = build_graph()
