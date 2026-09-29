import re

import httpx

from web_search_agent.services.providers.base import SearchHit, SearchProvider, SearchQuery

_TAG = re.compile(r"<[^>]+>")


class WikipediaProvider(SearchProvider):
    """Wikipedia's own search API (MediaWiki ``list=search``): free, no key, well-sourced articles.

    Searched on every query next to the web provider (``WEB_SEARCH_ALWAYS_PROVIDERS``); the article pages are then
    read like any other page.
    """

    name = "wikipedia"

    def __init__(self, client: httpx.AsyncClient, language: str, timeout: float):
        self._client = client
        self._api = f"https://{language}.wikipedia.org/w/api.php"
        self._base = f"https://{language}.wikipedia.org/wiki/"
        self._timeout = timeout

    async def search(self, query: SearchQuery) -> list[SearchHit]:
        response = await self._client.get(
            self._api,
            params={"action": "query", "list": "search", "srsearch": query.text, "srlimit": min(query.max_results, 5),
                    "format": "json", "utf8": 1},
            timeout=self._timeout,
        )
        response.raise_for_status()
        results = response.json().get("query", {}).get("search", [])
        return [
            SearchHit(
                url=self._base + item["title"].replace(" ", "_"),
                title=item["title"],
                snippet=_TAG.sub("", item.get("snippet") or ""),
                published_date=item.get("timestamp"),
                provider=self.name,
            )
            for item in results
            if item.get("title")
        ]
