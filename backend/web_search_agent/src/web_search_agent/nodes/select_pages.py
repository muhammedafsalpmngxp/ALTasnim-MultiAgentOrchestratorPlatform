"""Join point after the parallel searches: merge the results and choose which pages to fetch."""

import asyncio
import itertools
import time

from langgraph.config import get_stream_writer
from langgraph.runtime import get_runtime

from web_search_agent.context import Context, resolve
from web_search_agent.services.urls import get_domain, is_trusted, normalize_url
from web_search_agent.settings import get_settings
from web_search_agent.state import State
from web_search_agent.steps import StepReporter, plural, span_seconds
from web_search_agent.tools import search_api


def _merge(results: list[dict], limit: int) -> tuple[list[dict], list[str], list[str]]:
    """Interleave hits (best of each query first), de-duplicate, cap."""
    ordered = sorted(results, key=lambda r: r["index"])
    providers = [r["provider"] for r in ordered if r["provider"]]
    warnings = list(dict.fromkeys(w for r in ordered for w in r["warnings"]))
    seen: set[str] = set()
    hits: list[dict] = []
    for hit in itertools.chain.from_iterable(itertools.zip_longest(*(r["hits"] for r in ordered))):
        if hit is None:
            continue
        key = normalize_url(hit["url"])
        if key not in seen:
            seen.add(key)
            hits.append(hit)
    return hits[:limit], list(dict.fromkeys(providers)), warnings


async def select_pages(state: State) -> dict:
    runtime = get_runtime(Context)
    reporter = StepReporter(get_stream_writer())
    settings = get_settings()
    ctx = resolve(runtime)
    hits, providers, warnings = _merge(state.get("search_results", []), settings.max_total_results)

    if not hits and state.get("effective_freshness") and not state.get("freshness"):
        # The planner's date filter was too strict; search again without it.
        reporter.report("search", "running", "No recent results - retrying without the date filter")
        started = time.time()
        retry = await asyncio.gather(
            *(
                search_api.web_search.ainvoke(
                    {
                        "query": query,
                        "max_results": settings.search_results_per_query,
                        "include_domains": state.get("include_domains") or [],
                        "exclude_domains": state.get("exclude_domains") or [],
                    }
                )
                for query in state["queries"]
            )
        )
        hits, providers, warnings = _merge(
            [{"index": i, **r} for i, r in enumerate(retry)], settings.max_total_results
        )
        search_seconds = (span_seconds(state.get("spans", {}), "search") or 0) + time.time() - started
    else:
        search_seconds = span_seconds(state.get("spans", {}), "search")

    update: dict = {"hits": hits, "fetch_urls": [], "provider_used": ",".join(providers) or None, "warnings": warnings}
    if not hits:
        steps = reporter.report("search", "failed", "No results from any provider", duration_s=search_seconds)
        steps.update(reporter.skip(["extract", "chunk", "rerank"], "not run: no search results"))
        update["step_state"] = steps
        return update

    # Sample hits are placeholders (no real page behind them): rank their snippets without downloading.
    # Trusted sources (Wikipedia, gov, major news, ...) are read first; the rest keep the search order.
    readable = [hit for hit in hits if hit.get("provider") != "sample"]
    readable.sort(key=lambda hit: not is_trusted(get_domain(hit["url"]), settings.trusted_domain_list))
    to_fetch = readable[: ctx.max_pages_to_fetch]
    steps = reporter.report(
        "search", "done", f"{plural(len(hits), 'result')} via {', '.join(providers)}",
        [f"{get_domain(hit['url'])} - {hit['title']}"[:90] for hit in hits[:6]],
        duration_s=search_seconds,
    )
    if to_fetch:
        reporter.report("extract", "running", f"Downloading {plural(len(to_fetch), 'page')}")
    update["fetch_urls"] = [hit["url"] for hit in to_fetch]
    update["step_state"] = steps
    return update
