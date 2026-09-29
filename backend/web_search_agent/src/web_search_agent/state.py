"""Graph state.

Input  ``{"task": AgentTask}``   from the orchestrator (the supervisor's plan step)  -> utils.AgentInput
Output ``{"result": {...}}``     to the orchestrator, which hands it to the verifier  -> utils.AgentOutput
State  everything the nodes share (private), with reducers for the parallel branches
SearchTask / PageTask            payloads of the Send() fan-outs
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from utils import AgentInput, AgentOutput
from web_search_agent.schemas import Freshness


# --- reducers for values written by parallel branches ------------------------------
def merge_dicts(left: dict | None, right: dict | None) -> dict:
    return {**(left or {}), **(right or {})}


def merge_spans(left: dict | None, right: dict | None) -> dict:
    """Wall-clock span of a step that runs as several parallel tasks: earliest start, latest end."""
    merged = dict(left or {})
    for step_id, span in (right or {}).items():
        current = merged.get(step_id)
        merged[step_id] = (
            span
            if current is None
            else {"start": min(current["start"], span["start"]), "end": max(current["end"], span["end"])}
        )
    return merged


class State(AgentInput, AgentOutput, total=False):
    """Private state. Only ``task`` (in) and ``result`` (out) are visible to the orchestrator."""

    # from the task (plan_queries)
    query: str
    top_k: int
    freshness: Freshness | None
    include_domains: list[str]
    exclude_domains: list[str]
    trace_id: str
    source_agent: str
    started_at: float
    created_at: str
    # pipeline
    queries: list[str]
    effective_freshness: Freshness | None
    search_results: Annotated[list[dict], operator.add]  # one entry per parallel search task
    hits: list[dict]  # merged, de-duplicated search hits (SearchHit)
    provider_used: str | None
    fetch_urls: list[str]  # pages chosen for the extract fan-out
    pages: Annotated[dict[str, Any], merge_dicts]  # url -> extracted page (or None), from parallel fetches
    spans: Annotated[dict[str, dict], merge_spans]  # timing of the parallel steps
    step_state: Annotated[dict[str, dict], merge_dicts]  # step id -> PipelineStep
    reranker: str
    evidence: list[dict]  # Evidence
    sources: list[dict]  # Source
    context: str
    llm: dict  # LLMInfo
    warnings: Annotated[list[str], operator.add]
    details: dict  # full run for the UI (finalize -> send_output)


class SearchTask(TypedDict):
    index: int
    query: str
    freshness: Freshness | None
    include_domains: list[str]
    exclude_domains: list[str]


class PageTask(TypedDict):
    url: str
