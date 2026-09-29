import asyncio

from ddgs import DDGS

from web_search_agent.services.providers.base import SearchHit, SearchProvider, SearchQuery

_TIMELIMIT = {"day": "d", "week": "w", "month": "m", "year": "y"}


class DuckDuckGoProvider(SearchProvider):
    """DuckDuckGo via the unofficial `ddgs` library. No API key; last-resort fallback (rate limited)."""

    name = "duckduckgo"

    def __init__(self, timeout: float):
        self._timeout = int(timeout)

    async def search(self, query: SearchQuery) -> list[SearchHit]:
        def run() -> list[dict]:
            return DDGS(timeout=self._timeout).text(
                query.text_with_site_filters(),
                max_results=query.max_results,
                timelimit=_TIMELIMIT.get(query.freshness or ""),
            )

        results = await asyncio.to_thread(run)
        return [
            SearchHit(
                url=item["href"],
                title=item.get("title") or item["href"],
                snippet=item.get("body") or "",
                provider=self.name,
            )
            for item in results or []
            if item.get("href")
        ]
