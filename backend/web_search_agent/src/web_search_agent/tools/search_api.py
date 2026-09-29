import json
from dataclasses import asdict

from cachetools import TTLCache
from langchain_core.tools import tool

from web_search_agent.schemas import Freshness
from web_search_agent.services.providers import SearchQuery
from web_search_agent.services.resources import search_service
from web_search_agent.settings import get_settings

_cache: TTLCache[str, dict] = TTLCache(maxsize=512, ttl=get_settings().search_cache_ttl_seconds)


@tool("web_search")
async def web_search(
    query: str,
    max_results: int = 8,
    freshness: Freshness | None = None,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
) -> dict:
    """Search the live web. Tries Tavily, then SearXNG, then DuckDuckGo until one returns results.

    Returns {"provider": str | None, "hits": [{url, title, snippet, published_date, provider}], "warnings": [str]}.
    """
    key = json.dumps([query.lower().strip(), max_results, freshness, include_domains, exclude_domains])
    if key in _cache:
        return _cache[key]

    hits, provider, warnings = await search_service().search(
        SearchQuery(
            text=query,
            max_results=max_results,
            freshness=freshness,
            include_domains=include_domains or [],
            exclude_domains=exclude_domains or [],
        )
    )
    result = {"provider": provider, "hits": [asdict(hit) for hit in hits], "warnings": warnings}
    if hits:
        _cache[key] = result
    return result
