"""Agent card: the supervisor reads this to decide when to use this agent."""

from __future__ import annotations

from pydantic import BaseModel, Field

from utils import AgentCard


class WebSearchParams(BaseModel):
    query: str | None = Field(default=None, description="Explicit search query. Defaults to the step objective.")
    region: str | None = Field(default=None, description="Country or city to focus on, e.g. 'Oman'.")
    max_sources: int = Field(default=5, ge=1, le=10)


class Finding(BaseModel):
    title: str
    url: str
    snippet: str
    query: str


class WebSearchResult(BaseModel):
    status: str
    summary: str
    findings: list[Finding]
    sources: list[str]


CARD = AgentCard(
    name="web_search",
    version="0.1.0",
    description="Searches the public web and returns findings with source URLs.",
    when_to_use="Current prices, news, product information, public facts, anything not held in internal systems.",
    when_not_to_use="Internal company data (use data agent), sending messages (use communication agent).",
    examples=[
        "What is the price of iPhone 16?",
        "Latest news about competitor X",
        "Compare iPhone price in Oman and UAE",
    ],
    approval_mode="none",
    params_schema=WebSearchParams.model_json_schema(),
    output_schema=WebSearchResult.model_json_schema(),
    owner="team-search",
)
