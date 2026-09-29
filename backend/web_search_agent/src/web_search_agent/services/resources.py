"""Shared, lazily-created resources used by the tools and nodes.

httpx clients and asyncio semaphores belong to one event loop, so those are created per running loop
(the LangGraph server uses one loop; tests may create several). The reranker model is process-wide.
"""

import asyncio
import threading

import httpx

from web_search_agent.services.providers import (
    DuckDuckGoProvider,
    GoogleProvider,
    SampleProvider,
    SearchProvider,
    SearxngProvider,
    TavilyProvider,
    WikipediaProvider,
)
from web_search_agent.services.reranker import Reranker
from web_search_agent.services.scraper import Scraper
from web_search_agent.services.search_service import SearchService
from web_search_agent.settings import get_settings


class _LoopResources:
    def __init__(self) -> None:
        settings = get_settings()
        self.client = httpx.AsyncClient(
            headers={"User-Agent": settings.user_agent, "Accept-Language": "en-US,en;q=0.9"},
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
        )
        self.search = SearchService(_providers(self.client), _always(self.client), settings.blocked_domain_list,
                                    settings.always_results_per_query)
        self.scraper = Scraper(self.client, settings)


def _providers(client: httpx.AsyncClient) -> list[SearchProvider]:
    settings = get_settings()
    available: dict[str, SearchProvider] = {
        "tavily": TavilyProvider(client, settings.tavily_api_key, settings.search_timeout_seconds),
        "google": GoogleProvider(client, settings.google_api_key, settings.google_cse_id,
                                 settings.search_timeout_seconds),
        "searxng": SearxngProvider(client, settings.searxng_url, settings.search_timeout_seconds),
        "duckduckgo": DuckDuckGoProvider(settings.search_timeout_seconds),
        "sample": SampleProvider(),
    }
    return [available[name] for name in settings.provider_order if name in available]


def _always(client: httpx.AsyncClient) -> list[SearchProvider]:
    """Searched on every query next to the chain above (WEB_SEARCH_ALWAYS_PROVIDERS)."""
    settings = get_settings()
    available = {"wikipedia": WikipediaProvider(client, settings.wikipedia_language, settings.search_timeout_seconds)}
    return [available[name] for name in settings.always_provider_order if name in available]


_per_loop: dict[int, _LoopResources] = {}
_reranker: Reranker | None = None
_reranker_lock = threading.Lock()


def _loop_resources() -> _LoopResources:
    loop_id = id(asyncio.get_running_loop())
    if loop_id not in _per_loop:
        _per_loop[loop_id] = _LoopResources()
    return _per_loop[loop_id]


def http_client() -> httpx.AsyncClient:
    return _loop_resources().client


def search_service() -> SearchService:
    return _loop_resources().search


def scraper() -> Scraper:
    return _loop_resources().scraper


def reranker() -> Reranker:
    global _reranker
    with _reranker_lock:
        if _reranker is None:
            _reranker = Reranker(get_settings())
        return _reranker


def providers_status() -> list[dict]:
    """Provider configuration without needing an event loop (for /custom/health)."""
    settings = get_settings()
    configured = {
        "tavily": bool(settings.tavily_api_key),
        "google": bool(settings.google_api_key and settings.google_cse_id),
        "searxng": bool(settings.searxng_url),
        "duckduckgo": True,
        "sample": True,
    }
    chain = [{"name": name, "configured": configured.get(name, False)} for name in settings.provider_order]
    also = [{"name": name, "configured": True, "always": True} for name in settings.always_provider_order
            if name == "wikipedia" and not settings.offline]
    return chain + also
