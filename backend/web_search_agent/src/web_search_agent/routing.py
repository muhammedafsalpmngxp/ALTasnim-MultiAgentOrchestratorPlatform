"""Fan-out functions for add_conditional_edges: each returns one Send per parallel task."""

from __future__ import annotations

from langgraph.types import Send

from web_search_agent.state import PageTask, SearchTask, State


def fan_out_search(state: State) -> list[Send]:
    """plan_queries -> one `search` task per planned query (LangGraph map-reduce with ``Send``)."""
    return [
        Send(
            "search",
            SearchTask(
                index=index,
                query=query,
                freshness=state.get("effective_freshness"),
                include_domains=state.get("include_domains") or [],
                exclude_domains=state.get("exclude_domains") or [],
            ),
        )
        for index, query in enumerate(state["queries"])
    ]


def fan_out_fetch(state: State) -> list[Send] | str:
    """select_pages -> one `extract` task per page to read; `rank` when there is nothing to download
    (sample hits: rank their snippets); `finalize` when nothing was found at all."""
    if not state.get("hits"):
        return "finalize"
    urls = state.get("fetch_urls", [])
    if not urls:
        return "rank"
    return [Send("extract", PageTask(url=url)) for url in urls]
