import httpx

from web_search_agent.services.providers.base import SearchHit, SearchProvider, SearchQuery


class SearxngProvider(SearchProvider):
    """Self-hosted SearXNG metasearch (free, unlimited). `json` must be listed in `search.formats` of settings.yml."""

    name = "searxng"

    def __init__(self, client: httpx.AsyncClient, base_url: str | None, timeout: float):
        self._client = client
        self._base_url = base_url.rstrip("/") if base_url else None
        self._timeout = timeout

    @property
    def is_configured(self) -> bool:
        return bool(self._base_url)

    async def search(self, query: SearchQuery) -> list[SearchHit]:
        params = {"q": query.text_with_site_filters(), "format": "json", "safesearch": 1}
        if query.freshness:
            params["time_range"] = query.freshness

        response = await self._client.get(f"{self._base_url}/search", params=params, timeout=self._timeout)
        response.raise_for_status()
        return [
            SearchHit(
                url=item["url"],
                title=item.get("title") or item["url"],
                snippet=item.get("content") or "",
                published_date=item.get("publishedDate"),
                provider=self.name,
            )
            for item in response.json().get("results", [])[: query.max_results]
            if item.get("url")
        ]
