"""Value objects carried in the graph state and the agent result (serialised with `.model_dump()`).

The graph's input/output contract is the platform's ``utils.AgentInput`` / ``utils.AgentOutput``;
the fields of ``result`` are described by ``card.WebSearchResult``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Freshness = Literal["day", "week", "month", "year"]
ExtractionMethod = Literal["trafilatura", "playwright+trafilatura", "snippet"]
StepId = Literal["plan", "search", "extract", "chunk", "rerank", "verify"]
StepStatus = Literal["pending", "running", "done", "skipped", "failed"]


class Evidence(BaseModel):
    rank: int = Field(..., description="1 = most relevant.")
    citation_id: int = Field(..., description="Matches `Source.citation_id`.")
    title: str
    url: str
    domain: str
    published_date: str | None = None
    content: str = Field(..., description="The relevant passage extracted from the page.")
    relevance_score: float = Field(..., description="Reranker relevance, 0-1.")
    final_score: float = Field(..., description="Relevance blended with recency, 0-1. Evidence is sorted by this.")
    extraction_method: ExtractionMethod


class Source(BaseModel):
    citation_id: int
    title: str
    url: str
    domain: str
    published_date: str | None = None
    author: str | None = None


class LLMInfo(BaseModel):
    planner_model: str | None = Field(None, description="Model that planned the search queries, if any.")


class PipelineStep(BaseModel):
    """One box of the processing flow shown in the UI (streamed live as custom events)."""

    id: StepId
    title: str
    status: StepStatus = "pending"
    duration_s: float | None = Field(None, description="Seconds this step took (null if it did not run).")
    detail: str = Field("", description="One-line summary, e.g. '12 results via tavily'.")
    items: list[str] = Field(
        default_factory=list, description="Short list shown under the box (queries, domains, ...)."
    )


class Timings(BaseModel):
    """All values in seconds."""

    plan_s: float = 0.0
    search_s: float = 0.0
    extract_s: float = 0.0
    chunk_s: float = 0.0
    rerank_s: float = 0.0
    total_s: float = 0.0

