from __future__ import annotations

import re

from web_search_agent.services.providers.base import SearchHit, SearchProvider, SearchQuery


class SampleProvider(SearchProvider):
    """Deterministic offline results, so the whole platform (and CI) runs without network or keys.

    Titles are marked ``[SAMPLE DATA]``: the verifier flags them with a warning. Pages are never downloaded.
    Set ``WEB_SEARCH_PROVIDERS=tavily,searxng,duckduckgo`` for real results.
    """

    name = "sample"

    async def search(self, query: SearchQuery) -> list[SearchHit]:
        slug = re.sub(r"[^a-z0-9]+", "-", query.text.lower()).strip("-")[:60]
        return [
            SearchHit(
                url=f"https://example.com/sample/{slug}/{i + 1}",
                title=f"[SAMPLE DATA] {query.text}: result {i + 1}",
                snippet=(f"Sample snippet {i + 1} for '{query.text}'. "
                         "Set WEB_SEARCH_PROVIDERS in backend/.env for real web results."),
                provider=self.name,
            )
            for i in range(min(query.max_results, 3))
        ]
