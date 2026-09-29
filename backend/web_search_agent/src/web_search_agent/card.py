"""Agent card: the supervisor reads this to decide when to use this agent and which params to send."""

from __future__ import annotations

from pydantic import BaseModel, Field

from utils import AgentCard
from web_search_agent import __version__
from web_search_agent.schemas import Freshness


class WebSearchParams(BaseModel):
    """``AgentTask.params`` set by the supervisor. Everything is optional; the objective is searched by default."""

    query: str | None = Field(default=None, description="Explicit search query. Defaults to the step objective.")
    region: str | None = Field(default=None, description="Country or city to focus on, e.g. 'Oman'.")
    freshness: Freshness | None = Field(
        default=None, description="Only sources from the past day/week/month/year. Default: chosen by the planner."
    )
    include_domains: list[str] = Field(default_factory=list, description="Only search these domains.")
    exclude_domains: list[str] = Field(default_factory=list, description="Never use these domains.")


class TopContent(BaseModel):
    rank: int = Field(description="1 = most relevant.")
    title: str
    url: str
    content: str = Field(description="The passage extracted from the page.")


class WebSearchResult(BaseModel):
    """``result`` returned to the orchestrator, which passes it to the verifier (and later steps) as an input:
    only the input question and the top contents, plus the platform's required ``status`` / ``summary``."""

    status: str = Field(description="ok | failed (no results)")
    summary: str = Field(description="The question and the top contents as readable text (chat answer, emails).")
    question: str = Field(description="The question that was searched (objective / query, with the region).")
    findings: list[TopContent] = Field(description="The top 3 ranked contents, best first.")
    sources: list[str] = Field(description="URLs of the top contents, in the same order.")


CARD = AgentCard(
    name="web_search",
    version=__version__,
    description=(
        "Searches the live public web: plans focused queries, searches them in parallel, reads the pages and "
        "reranks the passages. Returns the question and the top 3 most relevant passages with their source URLs."
    ),
    when_to_use=(
        "Current or time-sensitive public information: prices, news, releases, 'latest', 'today', facts after "
        "the LLM's training cutoff, or public facts that are not in internal systems. Use one step per distinct "
        "subject or region (e.g. one per country when comparing), so they run in parallel. Can run after the RAG "
        "agent (depends_on) when internal documents are missing or unsure: it then searches for what the RAG "
        "result did not cover (it reads 'answer'/'summary' and searches 'search_query'/'search_queries')."
    ),
    when_not_to_use=(
        "Internal or company-private data (use the RAG / data agent), sending messages (use the communication "
        "agent), or questions answerable without fresh information."
    ),
    examples=[
        "What is the price of iPhone 16?",
        "Find iPhone price in Oman (params: query='iPhone price', region='Oman')",
        "Latest developments in solid-state batteries (params: freshness='month')",
        "ECB interest rate decision (params: include_domains=['ecb.europa.eu', 'reuters.com'])",
        "Our leave policy vs. the UAE labour law: rag step s1, then web_search 'UAE labour law annual leave' "
        "with depends_on=['s1']",
    ],
    approval_mode="none",  # read-only on public data
    params_schema=WebSearchParams.model_json_schema(),
    output_schema=WebSearchResult.model_json_schema(),
    owner="team-search",
)
