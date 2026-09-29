"""Per-run context (LangGraph ``context_schema``).

The platform's ``RequestContext`` (tenant, user, roles, locale) plus optional web-search knobs. The orchestrator
sends only ``RequestContext``; the knobs are for LangGraph Studio, tests and this agent's own UI routes.
Anything unset falls back to the deployment settings (``WEB_SEARCH_*`` in ``backend/.env``).
"""

from __future__ import annotations

from dataclasses import dataclass

from langgraph.runtime import Runtime

from utils import RequestContext
from web_search_agent.settings import Settings, get_settings


class Context(RequestContext, total=False):
    fast_model: str
    max_search_queries: int
    max_pages_to_fetch: int
    top_k: int  # evidence passages ranked (the step result always carries the best WEB_SEARCH_RESULT_TOP_N)
    source_agent: str  # who started the run: "orchestrator" (default) or "web-search-ui"
    trace_id: str


@dataclass(frozen=True)
class ResolvedContext:
    fast_model: str
    max_search_queries: int
    max_pages_to_fetch: int
    top_k: int
    source_agent: str
    trace_id: str | None


def resolve(runtime: Runtime | None, settings: Settings | None = None) -> ResolvedContext:
    settings = settings or get_settings()
    ctx: dict = dict((runtime.context if runtime is not None else None) or {})  # None when the caller sends none
    return ResolvedContext(
        fast_model=ctx.get("fast_model") or settings.openai_fast_model,
        max_search_queries=ctx.get("max_search_queries") or settings.max_search_queries,
        max_pages_to_fetch=ctx.get("max_pages_to_fetch") or settings.max_pages_to_fetch,
        top_k=ctx.get("top_k") or max(5, settings.result_top_n),
        source_agent=ctx.get("source_agent") or "orchestrator",
        trace_id=ctx.get("trace_id"),
    )
