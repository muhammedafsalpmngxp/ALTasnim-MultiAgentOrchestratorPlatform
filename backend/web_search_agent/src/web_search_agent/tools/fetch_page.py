from dataclasses import asdict

from cachetools import TTLCache
from langchain_core.tools import tool

from web_search_agent.services.resources import scraper
from web_search_agent.settings import get_settings

_cache: TTLCache[str, dict] = TTLCache(maxsize=1024, ttl=get_settings().page_cache_ttl_seconds)


@tool("fetch_page")
async def fetch_page(url: str) -> dict | None:
    """Download a web page and extract its main text with Trafilatura (JS rendering via Playwright if enabled).

    Respects robots.txt and a hard per-page deadline. Returns {url, text, title, author, published_date, method},
    or None if the page could not be fetched or had no readable content.
    """
    if url in _cache:
        return _cache[url]
    page = await scraper().extract(url)
    if page is None:
        return None
    result = asdict(page)
    _cache[url] = result
    return result
