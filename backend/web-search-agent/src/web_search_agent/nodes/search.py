"""One search query. Runs once per query, in parallel (dispatched with ``Send``)."""

from __future__ import annotations

from utils.events import emit
from web_search_agent.tools.search_provider import get_search_provider


def search(job: dict) -> dict:
    emit("progress", agent="web_search", message=f"Searching: {job['query']}")
    hits = get_search_provider().search(job["query"], job.get("max_sources", 5))
    return {"findings": hits}
