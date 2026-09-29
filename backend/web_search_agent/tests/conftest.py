"""Fixtures for the web-search-agent tests: offline settings, fake chat model, fake search / fetch tools.

Every test runs with the defaults (``WEB_SEARCH_PROVIDERS=sample``, no LLM) whatever ``backend/.env`` contains,
and never downloads the cross-encoder. ``fake_web`` swaps in live-looking search hits and page fetches.
"""

from __future__ import annotations

import os

import pytest
from langchain_core.runnables import RunnableLambda
from langchain_core.tools import tool
from web_search_agent.nodes import rank as rank_node
from web_search_agent.services import history, resources
from web_search_agent.services.reranker import Reranker
from web_search_agent.settings import ENV_PREFIX, get_settings
from web_search_agent.tools import fetch_page, search_api

from web_search_agent import llm

ARTICLE = "\n\n".join(
    [
        "Solid-state batteries replace the liquid electrolyte with a solid one, improving safety.",
        " ".join(["Researchers reported a new sulfide electrolyte that raises energy density."] * 8),
        " ".join(["Automakers plan pilot production of solid-state cells within two years."] * 8),
    ]
)


class FakeChatModel:
    """Stands in for ChatOpenAI. `responses[SchemaClass]` is returned (or raised, if it is an exception, or
    popped in order if it is a list) whenever a node asks for that structured output."""

    def __init__(self):
        self.responses: dict[type, object] = {}
        self.calls: list[tuple[str, str, str]] = []  # (tier, model, schema)

    def for_call(self, tier: str, model: str) -> FakeChatModel._Bound:
        return FakeChatModel._Bound(self, tier, model)

    class _Bound:
        def __init__(self, parent: FakeChatModel, tier: str, model: str):
            self.parent, self.tier, self.model = parent, tier, model

        def with_structured_output(self, schema, **_kwargs):
            async def respond(_messages):
                self.parent.calls.append((self.tier, self.model, schema.__name__))
                response = self.parent.responses[schema]
                if isinstance(response, list):
                    response = response.pop(0)
                if isinstance(response, Exception):
                    raise response
                return response

            return RunnableLambda(respond)


def fake_search_tool(calls: list[dict], results_per_query: int = 2, empty: bool = False):
    @tool("web_search")
    async def web_search(
        query: str,
        max_results: int = 8,
        freshness: str | None = None,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
    ) -> dict:
        """Fake web search: two hits per query, one page shared by every query (to test de-duplication)."""
        calls.append({"query": query, "freshness": freshness, "include_domains": include_domains})
        if empty:
            return {"provider": None, "hits": [], "warnings": ["fake returned no results"]}
        slug = "-".join(query.lower().split())[:30]
        hits = [
            {"url": "https://shared.example.com/solid-state", "title": "Shared battery article",
             "snippet": "Solid-state batteries overview", "published_date": "2026-09-20", "provider": "fake"},
            {"url": f"https://news.example.org/{slug}", "title": f"News about {query}",
             "snippet": f"Solid-state batteries snippet for {query}", "published_date": None, "provider": "fake"},
        ][:results_per_query]
        return {"provider": "fake", "hits": hits, "warnings": []}

    return web_search


def fake_fetch_tool(calls: list[str]):
    @tool("fetch_page")
    async def fetch_page(url: str) -> dict | None:
        """Fake fetch: the shared article is readable, every other page fails (snippet fallback)."""
        calls.append(url)
        if "shared.example.com" in url:
            return {"url": url, "text": ARTICLE, "title": "Shared battery article", "author": "A. Writer",
                    "published_date": "2026-09-20", "method": "trafilatura"}
        return None

    return fetch_page


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    """Default settings (sample provider, no LLM), a BM25-only reranker and a recording fetch tool."""
    for key in [k for k in os.environ if k.startswith(ENV_PREFIX)]:
        monkeypatch.delenv(key)  # ignore WEB_SEARCH_* from backend/.env
    monkeypatch.setenv(f"{ENV_PREFIX}RERANKER_PRELOAD", "false")
    monkeypatch.setenv(f"{ENV_PREFIX}CHECKPOINT_DIR", str(tmp_path / "checkpoints"))  # never the real logs/
    get_settings.cache_clear()

    bm25 = Reranker(get_settings())
    bm25._load_attempted = True  # never download the cross-encoder
    monkeypatch.setattr(rank_node, "reranker", lambda: bm25)
    monkeypatch.setattr(resources, "reranker", lambda: bm25)

    fetch_calls: list[str] = []
    monkeypatch.setattr(fetch_page, "fetch_page", fake_fetch_tool(fetch_calls))
    history.clear()
    yield {"fetch_calls": fetch_calls, "search_calls": []}
    get_settings.cache_clear()


@pytest.fixture
def fake_web(offline, monkeypatch):
    """Live-looking search results (provider 'fake') instead of the sample provider."""
    monkeypatch.setattr(search_api, "web_search", fake_search_tool(offline["search_calls"]))

    def no_results():
        monkeypatch.setattr(search_api, "web_search", fake_search_tool(offline["search_calls"], empty=True))

    return {**offline, "no_results": no_results}


@pytest.fixture
def fake_llm(monkeypatch):
    """Turns the LLM on and routes both tiers to one FakeChatModel; set `.responses[Schema]` per test."""
    model = FakeChatModel()
    monkeypatch.setattr(llm, "is_configured", lambda: True)
    monkeypatch.setattr(llm, "get_chat_model", lambda tier, name: model.for_call(tier, name))
    return model
