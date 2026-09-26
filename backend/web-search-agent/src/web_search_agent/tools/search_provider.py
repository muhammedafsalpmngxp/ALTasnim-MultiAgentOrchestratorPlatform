"""Search provider interface.

TODO(team-search): add a real provider (Tavily, Bing, Google CSE, SerpAPI, ...)
behind the same ``search()`` signature and select it with SEARCH_PROVIDER.
The ``sample`` provider returns clearly labelled offline data for development.
"""

from __future__ import annotations

import os
import re
from typing import Protocol


class SearchProvider(Protocol):
    def search(self, query: str, max_results: int) -> list[dict]: ...


class SampleSearchProvider:
    """Deterministic offline results so the whole platform runs without keys."""

    def search(self, query: str, max_results: int) -> list[dict]:
        slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")[:60]
        return [
            {
                "title": f"[SAMPLE DATA] {query}: result {i + 1}",
                "url": f"https://example.com/sample/{slug}/{i + 1}",
                "snippet": f"Sample snippet {i + 1} for '{query}'. Configure SEARCH_PROVIDER for real results.",
                "query": query,
            }
            for i in range(min(max_results, 3))
        ]


def get_search_provider() -> SearchProvider:
    name = os.getenv("SEARCH_PROVIDER", "sample")
    if name == "sample":
        return SampleSearchProvider()
    raise ValueError(f"Unknown SEARCH_PROVIDER={name!r}. Implement it in tools/search_provider.py.")
