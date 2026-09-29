import httpx

from web_search_agent.services.providers.base import SearchHit, SearchProvider, SearchQuery

TAVILY_SEARCH_URL = "https://api.tavily.com/search"


class TavilyProvider(SearchProvider):
    """Tavily: search API built for LLM agents (free tier ~1,000 credits/month)."""

    name = "tavily"

    def __init__(self, client: httpx.AsyncClient, api_key: str | None, timeout: float):
        self._client = client
        self._api_key = api_key
        self._timeout = timeout

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def search(self, query: SearchQuery) -> list[SearchHit]:
        payload: dict = {
            "query": query.text,
            "max_results": min(query.max_results, 20),
            "search_depth": "basic",
            "include_answer": False,
            "include_raw_content": False,  # page content is extracted by our own Trafilatura step
        }
        if query.freshness:
            payload["time_range"] = query.freshness
        if query.include_domains:
            payload["include_domains"] = query.include_domains
        if query.exclude_domains:
            payload["exclude_domains"] = query.exclude_domains

        response = await self._client.post(
            TAVILY_SEARCH_URL,
            json=payload,
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=self._timeout,
        )
        response.raise_for_status()
        return [
            SearchHit(
                url=item["url"],
                title=item.get("title") or item["url"],
                snippet=item.get("content") or "",
                published_date=item.get("published_date"),
                provider=self.name,
            )
            for item in response.json().get("results", [])
            if item.get("url")
        ]
