"""One search query. Runs once per planned query, in parallel (Send fan-out from routing.fan_out_search)."""

import time

from langgraph.config import get_stream_writer

from web_search_agent.settings import get_settings
from web_search_agent.state import SearchTask
from web_search_agent.steps import StepReporter, span
from web_search_agent.tools import search_api


async def search(task: SearchTask) -> dict:
    reporter = StepReporter(get_stream_writer())
    started = time.time()
    reporter.report("search", "running", f'Searching "{task["query"]}"')

    result = await search_api.web_search.ainvoke(
        {
            "query": task["query"],
            "max_results": get_settings().search_results_per_query,
            "freshness": task["freshness"],
            "include_domains": task["include_domains"],
            "exclude_domains": task["exclude_domains"],
        }
    )
    provider = result["provider"] or "no provider"
    reporter.report("search", "running", f'"{task["query"]}" -> {len(result["hits"])} results via {provider}')
    return {
        "search_results": [{"index": task["index"], "query": task["query"], **result}],
        "spans": {"search": span(started)},
    }
