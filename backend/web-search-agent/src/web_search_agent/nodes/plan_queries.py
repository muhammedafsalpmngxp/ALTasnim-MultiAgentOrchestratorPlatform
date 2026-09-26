"""Turn the step objective into 1-3 search queries (LLM if configured, else rules)."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from utils import AgentTask
from utils.llm import get_model
from web_search_agent.card import WebSearchParams
from web_search_agent.state import State

PROMPT = (Path(__file__).parent.parent / "prompts" / "plan_queries.md").read_text(encoding="utf-8")


class Queries(BaseModel):
    items: list[str] = Field(min_length=1, max_length=3)


def rule_based_queries(base: str) -> list[str]:
    queries = [base]
    if "price" in base.lower():
        queries.append(f"{base} official store")
    return queries[:3]


def plan_queries(state: State) -> dict:
    task = AgentTask.model_validate(state["task"])
    params = WebSearchParams.model_validate(task.params)
    base = params.query or task.objective
    if params.region and params.region.lower() not in base.lower():
        base = f"{base} in {params.region}"

    model = get_model("fast")
    if model is None:
        queries = rule_based_queries(base)
    else:
        queries = model.with_structured_output(Queries).invoke(PROMPT.format(objective=base)).items

    return {"queries": queries, "max_sources": params.max_sources}
