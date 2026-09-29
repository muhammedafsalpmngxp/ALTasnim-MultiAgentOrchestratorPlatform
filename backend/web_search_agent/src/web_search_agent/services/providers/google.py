import httpx

from web_search_agent.services.providers.base import SearchHit, SearchProvider, SearchQuery

GOOGLE_SEARCH_URL = "https://www.googleapis.com/customsearch/v1"
_DATE_RESTRICT = {"day": "d1", "week": "w1", "month": "m1", "year": "y1"}


class GoogleProvider(SearchProvider):
    """Google results via the Programmable Search JSON API (free: 100 queries/day).

    Needs ``WEB_SEARCH_GOOGLE_API_KEY`` (https://developers.google.com/custom-search/v1/introduction) and
    ``WEB_SEARCH_GOOGLE_CSE_ID`` (a search engine set to "search the entire web": https://programmablesearchengine.google.com).
    Skipped when either is missing.
    """

    name = "google"

    def __init__(self, client: httpx.AsyncClient, api_key: str | None, cse_id: str | None, timeout: float):
        self._client = client
        self._api_key = api_key
        self._cse_id = cse_id
        self._timeout = timeout

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key and self._cse_id)

    async def search(self, query: SearchQuery) -> list[SearchHit]:
        params: dict = {"key": self._api_key, "cx": self._cse_id, "q": query.text_with_site_filters(),
                        "num": min(query.max_results, 10)}
        if query.freshness in _DATE_RESTRICT:
            params["dateRestrict"] = _DATE_RESTRICT[query.freshness]
        response = await self._client.get(GOOGLE_SEARCH_URL, params=params, timeout=self._timeout)
        response.raise_for_status()
        return [
            SearchHit(url=item["link"], title=item.get("title") or item["link"], snippet=item.get("snippet") or "",
                      provider=self.name)
            for item in response.json().get("items", [])
            if item.get("link")
        ]
