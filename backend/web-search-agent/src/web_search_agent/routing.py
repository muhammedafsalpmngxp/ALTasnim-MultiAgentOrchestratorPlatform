from __future__ import annotations

from langgraph.types import Send

from web_search_agent.state import State


def fan_out_searches(state: State) -> list[Send]:
    """One parallel ``search`` branch per query (LangGraph map-reduce with ``Send``)."""
    return [Send("search", {"query": q, "max_sources": state.get("max_sources", 5)}) for q in state["queries"]]
