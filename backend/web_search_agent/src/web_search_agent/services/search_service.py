import asyncio
import dataclasses
import itertools
import logging

from web_search_agent.services.providers import SearchHit, SearchProvider, SearchQuery
from web_search_agent.services.urls import domain_matches, get_domain, normalize_url

logger = logging.getLogger(__name__)


class SearchService:
    """Tries each configured provider in order and uses the first non-empty result set; the ``always`` providers
    (Wikipedia) are searched at the same time and merged in first. ``blocked`` domains are never returned."""

    def __init__(self, providers: list[SearchProvider], always: list[SearchProvider] | None = None,
                 blocked: list[str] | None = None, always_limit: int = 2):
        self.providers = providers
        self.always = always or []
        self.blocked = blocked or []
        self.always_limit = always_limit  # results per query from each `always` provider

    async def search(self, query: SearchQuery) -> tuple[list[SearchHit], str | None, list[str]]:
        live = any(p.name != "sample" and p.is_configured for p in self.providers)
        extra = [p for p in self.always if p.is_configured] if live else []  # never with offline sample data
        chain, *side = await asyncio.gather(self._first(query), *(self._one(p, query) for p in extra))
        hits, provider, warnings = chain
        names = [provider] if provider else []
        merged: list[SearchHit] = []
        for (extra_hits, extra_warnings), p in zip(side, extra, strict=True):
            warnings += extra_warnings
            if extra_hits:
                merged += extra_hits
                names.append(p.name)
        return self._dedupe(merged + hits), ",".join(names) or None, warnings

    async def _one(self, provider: SearchProvider, query: SearchQuery) -> tuple[list[SearchHit], list[str]]:
        try:
            hits = await provider.search(query)
        except Exception as exc:  # noqa: BLE001 - an extra source failing must not fail the search
            logger.warning("Provider %s failed: %s", provider.name, exc)
            return [], [f"{provider.name} failed: {type(exc).__name__}"]
        return self._filter(self._dedupe(hits), query)[: self.always_limit], []

    async def _first(self, query: SearchQuery) -> tuple[list[SearchHit], str | None, list[str]]:
        warnings: list[str] = []
        for provider in self.providers:
            if not provider.is_configured:
                continue
            try:
                hits = await provider.search(query)
            except Exception as exc:  # noqa: BLE001 - any provider failure means "try the next one"
                logger.warning("Provider %s failed: %s", provider.name, exc)
                warnings.append(f"{provider.name} failed: {type(exc).__name__}")
                continue

            hits = self._filter(self._dedupe(hits), query)
            if hits:
                return hits[: query.max_results], provider.name, warnings
            warnings.append(f"{provider.name} returned no results")

        return [], None, warnings

    async def search_many(
        self, queries: list[str], template: SearchQuery, max_total: int
    ) -> tuple[list[SearchHit], list[str], list[str]]:
        """Run several queries concurrently and interleave their results (best of each query first)."""
        results = await asyncio.gather(
            *(self.search(dataclasses.replace(template, text=query)) for query in queries)
        )
        providers: list[str] = []
        warnings: list[str] = []
        for _, provider, query_warnings in results:
            if provider and provider not in providers:
                providers.append(provider)
            warnings.extend(w for w in query_warnings if w not in warnings)

        interleaved = [
            hit
            for row in itertools.zip_longest(*(hits for hits, _, _ in results))
            for hit in row
            if hit is not None
        ]
        return self._dedupe(interleaved)[:max_total], providers, warnings

    @staticmethod
    def _dedupe(hits: list[SearchHit]) -> list[SearchHit]:
        seen: set[str] = set()
        unique = []
        for hit in hits:
            key = normalize_url(hit.url)
            if key not in seen:
                seen.add(key)
                unique.append(hit)
        return unique

    def _filter(self, hits: list[SearchHit], query: SearchQuery) -> list[SearchHit]:
        # Applied for every provider, since only some support domain filters natively.
        result = []
        for hit in hits:
            if not hit.url.startswith(("http://", "https://")):
                continue
            domain = get_domain(hit.url)
            if query.include_domains and not domain_matches(domain, query.include_domains):
                continue
            if domain_matches(domain, query.exclude_domains) or domain_matches(domain, self.blocked):
                continue
            result.append(hit)
        return result
