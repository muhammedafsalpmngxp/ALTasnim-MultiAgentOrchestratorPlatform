"""Sources: Wikipedia on every search, Google, blocked social media, trusted sources first;
the reranker's local copy."""

import asyncio

import httpx
import pytest
from web_search_agent.services import reranker as reranker_module
from web_search_agent.services.providers import GoogleProvider, SearchHit, SearchQuery, WikipediaProvider
from web_search_agent.services.providers.base import SearchProvider
from web_search_agent.services.reranker import Candidate, Reranker
from web_search_agent.services.search_service import SearchService
from web_search_agent.services.urls import is_trusted
from web_search_agent.settings import Settings, get_settings

WIKI_JSON = {"query": {"search": [
    {"title": "Chief Minister of Kerala",
     "snippet": "The <span class=\"searchmatch\">Chief</span> Minister of Kerala is",
     "timestamp": "2026-09-01T10:00:00Z"},
    {"title": "Government of Kerala", "snippet": "is led by a chief minister"},
]}}


def serve(handler):
    async def run(coro_factory):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await coro_factory(client)
    return lambda f: asyncio.run(run(f))


def test_wikipedia_provider_uses_the_mediawiki_search_api():
    seen = []

    def handler(request):
        seen.append(request.url)
        return httpx.Response(200, json=WIKI_JSON)

    hits = serve(handler)(lambda c: WikipediaProvider(c, "en", 5).search(SearchQuery("who is the kerala cm", 5)))
    assert seen[0].host == "en.wikipedia.org" and seen[0].params["list"] == "search"
    assert [h.url for h in hits] == ["https://en.wikipedia.org/wiki/Chief_Minister_of_Kerala",
                                     "https://en.wikipedia.org/wiki/Government_of_Kerala"]
    assert hits[0].snippet == "The Chief Minister of Kerala is" and hits[0].provider == "wikipedia"


def test_google_provider_needs_a_key_and_an_engine_id():
    assert not GoogleProvider(None, None, None, 5).is_configured
    assert not GoogleProvider(None, "key", None, 5).is_configured

    def handler(request):
        assert request.url.params["cx"] == "cx1" and request.url.params["dateRestrict"] == "w1"
        return httpx.Response(200, json={"items": [{"link": "https://www.bbc.com/news/1", "title": "BBC",
                                                    "snippet": "s"}]})

    hits = serve(handler)(lambda c: GoogleProvider(c, "key", "cx1", 5).search(SearchQuery("q", 5, freshness="week")))
    assert [(h.url, h.provider) for h in hits] == [("https://www.bbc.com/news/1", "google")]


class Fixed(SearchProvider):
    def __init__(self, name, urls, fail=False):
        self.name, self._urls, self._fail = name, urls, fail

    async def search(self, query):
        if self._fail:
            raise httpx.ConnectError("down")
        return [SearchHit(url=u, title=u, provider=self.name) for u in self._urls]


def test_wikipedia_is_merged_first_and_social_media_is_blocked():
    web = Fixed("tavily", ["https://www.instagram.com/p/1", "https://www.thehindu.com/a", "https://m.facebook.com/x",
                           "https://www.tiktok.com/@a/video/1", "https://www.bbc.com/b"])
    wiki = Fixed("wikipedia", ["https://en.wikipedia.org/wiki/A", "https://en.wikipedia.org/wiki/B",
                               "https://en.wikipedia.org/wiki/C"])
    service = SearchService([web], [wiki], blocked=Settings().blocked_domain_list, always_limit=2)
    hits, provider, warnings = asyncio.run(service.search(SearchQuery("q", 5)))
    assert [h.url for h in hits] == ["https://en.wikipedia.org/wiki/A", "https://en.wikipedia.org/wiki/B",
                                     "https://www.thehindu.com/a", "https://www.bbc.com/b"]
    assert provider == "tavily,wikipedia" and warnings == []


def test_a_failing_extra_source_is_only_a_warning_and_sample_data_gets_no_extras():
    service = SearchService([Fixed("tavily", ["https://www.bbc.com/b"])], [Fixed("wikipedia", [], fail=True)])
    hits, provider, warnings = asyncio.run(service.search(SearchQuery("q", 5)))
    assert [h.url for h in hits] == ["https://www.bbc.com/b"] and warnings == ["wikipedia failed: ConnectError"]

    offline = SearchService([Fixed("sample", ["https://example.com/s"])], [Fixed("wikipedia", ["https://w/x"])])
    hits, provider, _ = asyncio.run(offline.search(SearchQuery("q", 5)))
    assert provider == "sample" and [h.url for h in hits] == ["https://example.com/s"]


@pytest.mark.parametrize("domain, trusted", [
    ("en.wikipedia.org", True), ("britannica.com", True), ("www.reuters.com", True), ("nasa.gov", True),
    ("india.gov.in", True), ("moh.gov.om", True), ("mit.edu", True), ("du.edu.om", True),
    ("governmentjobs.com", False), ("testbook.com", False), ("instagram.com", False), ("notwikipedia.org", False),
])
def test_trusted_domains(domain, trusted):
    assert is_trusted(domain, Settings().trusted_domain_list) is trusted


def test_trusted_sources_get_the_boost():
    reranker = Reranker(Settings(recency_weight=0.0, trusted_boost=0.3))
    reranker._load_attempted = True  # BM25 only
    ranked = reranker.rerank("kerala chief minister", [
        Candidate(text="kerala chief minister kerala chief minister named", source_key="1"),
        Candidate(text="kerala chief minister named today", source_key="2", trusted=True),
    ], top_k=2, cross_encoder=False)
    assert ranked[0].candidate.source_key == "2" and ranked[0].final_score > ranked[0].relevance


def test_the_reranker_is_downloaded_once_and_then_loaded_from_the_local_folder(tmp_path, monkeypatch):
    downloads = []

    def snapshot_download(repo_id, local_dir, allow_patterns):
        downloads.append(repo_id)
        (tmp_path / "cross-encoder--ms-marco-MiniLM-L-6-v2").mkdir()
        (tmp_path / "cross-encoder--ms-marco-MiniLM-L-6-v2" / "config.json").write_text("{}")
        assert "*.safetensors" in allow_patterns and not any("onnx" in p for p in allow_patterns)

    import huggingface_hub

    monkeypatch.setattr(huggingface_hub, "snapshot_download", snapshot_download)
    reranker = Reranker(Settings(reranker_dir=str(tmp_path)))
    first, second = reranker.local_path(), reranker.local_path()
    assert first == second == str(tmp_path / "cross-encoder--ms-marco-MiniLM-L-6-v2")
    assert downloads == ["cross-encoder/ms-marco-MiniLM-L-6-v2"]  # once
    assert reranker_module.AGENT_DIR.name == "web_search_agent"


def test_the_defaults_use_fewer_better_sources(monkeypatch):
    for key in ("WEB_SEARCH_MAX_PAGES_TO_FETCH", "WEB_SEARCH_RERANKER_MODEL"):
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()
    s = get_settings()
    assert s.max_pages_to_fetch == 4 and s.max_total_results == 8 and s.search_results_per_query == 5
    assert s.always_provider_order == ["wikipedia"] and "instagram.com" in s.blocked_domain_list
    assert s.reranker_model == "cross-encoder/ms-marco-MiniLM-L-6-v2"
