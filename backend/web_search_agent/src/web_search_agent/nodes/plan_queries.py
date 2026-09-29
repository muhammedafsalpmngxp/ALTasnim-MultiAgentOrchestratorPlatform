"""Entry node: read the supervisor's task (and any upstream results, e.g. from the RAG agent), then let the fast
model rewrite it into focused search queries.

Upstream results arrive in ``task.inputs`` (keyed by step id) when the plan makes this step depend on another one,
e.g. ``rag -> web_search`` when internal documents did not fully answer the question. From each result:
- ``search_query`` / ``search_queries``  are searched as well (the upstream agent knows what is missing),
- ``answer`` / ``summary``               tell the planner what is already known, so it searches for the gaps.

Transient OpenAI errors propagate so the node's RetryPolicy retries it; other failures (refusal, bad model id,
missing key) fall back to searching the question (+ upstream queries) as-is.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, date, datetime
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.config import get_stream_writer
from langgraph.runtime import get_runtime
from pydantic import BaseModel, Field

from utils import AgentTask
from web_search_agent import llm, prompts
from web_search_agent.card import WebSearchParams
from web_search_agent.context import Context, resolve
from web_search_agent.schemas import LLMInfo
from web_search_agent.settings import get_settings
from web_search_agent.state import State
from web_search_agent.steps import StepReporter, plural

logger = logging.getLogger(__name__)

UPSTREAM_TEXT_CHARS = 1500
prompts.load("plan_queries")  # read the prompt file now, not inside the event loop (blocking I/O)


class SearchPlan(BaseModel):
    queries: list[str] = Field(description="Search queries, most important first.")
    freshness: Literal["day", "week", "month", "year", "none"]


def question_from_task(task: AgentTask, params: WebSearchParams) -> str:
    """The step objective (or explicit query), focused on the region if one is given."""
    question = " ".join((params.query or task.objective).split())
    if params.region and params.region.lower() not in question.lower():
        question = f"{question} in {params.region}"
    return question


def upstream_hints(inputs: dict[str, Any]) -> tuple[list[str], str]:
    """Search queries and known facts from the results of the steps this one depends on (e.g. the RAG agent)."""
    queries: list[str] = []
    notes: list[str] = []
    for step_id, output in inputs.items():
        if not isinstance(output, dict):
            continue
        suggested = output.get("search_queries") or []
        if isinstance(suggested, str):
            suggested = [suggested]
        if output.get("search_query"):
            suggested = [output["search_query"], *suggested]
        queries += [" ".join(str(q).split()) for q in suggested if str(q).strip()]
        known = output.get("answer") or output.get("summary")
        if known:
            notes.append(f"[{step_id}] {str(known).strip()[:UPSTREAM_TEXT_CHARS]}")
    return _dedupe(queries), "\n\n".join(notes)


def _dedupe(queries: list[str]) -> list[str]:
    unique: list[str] = []
    for query in queries:
        query = " ".join(query.split())
        if query and query.lower() not in (q.lower() for q in unique):
            unique.append(query)
    return unique


def _planner_message(question: str, known: str, suggested: list[str]) -> str:
    if not known and not suggested:
        return question
    parts = [f"Question: {question}"]
    if known:
        parts.append(f"Already found by earlier agents (search for what is missing or needs confirming):\n{known}")
    if suggested:
        parts.append("Queries suggested by earlier agents: " + "; ".join(suggested))
    return "\n\n".join(parts)


async def plan_queries(state: State) -> dict:
    runtime = get_runtime(Context)
    reporter = StepReporter(get_stream_writer())
    reporter.announce()
    ctx = resolve(runtime)
    task = AgentTask.model_validate(state["task"])
    params = WebSearchParams.model_validate(task.params)
    started = time.time()
    question = question_from_task(task, params)
    suggested, known = upstream_hints(task.inputs)
    fallback = _dedupe([question, *suggested])[: ctx.max_search_queries]
    upstream = f" + input from {', '.join(task.inputs)}" if task.inputs else ""
    update: dict = {
        "query": question,
        "top_k": ctx.top_k,
        "freshness": params.freshness,
        "include_domains": params.include_domains,
        "exclude_domains": params.exclude_domains,
        "trace_id": ctx.trace_id or uuid.uuid4().hex,
        "source_agent": ctx.source_agent,
        "started_at": started,
        "created_at": datetime.now(UTC).isoformat(),
        "queries": fallback,
        "effective_freshness": params.freshness,
    }
    logger.info('▶ Search "%s"  (from %s, trace %s)', question[:120], ctx.source_agent, update["trace_id"][:8])

    if not llm.is_configured():
        update["step_state"] = reporter.report(
            "plan", "skipped", f"WEB_SEARCH_OPENAI_API_KEY not set - searching the question as-is{upstream}", fallback
        )
        return update
    if not get_settings().query_planning:
        update["step_state"] = reporter.report(
            "plan", "skipped", f"Query planning off - searching the question as-is{upstream}", fallback
        )
        return update

    reporter.report("plan", "running", f"{ctx.fast_model} is rewriting the question{upstream}")
    try:
        plan: SearchPlan = await llm.structured("fast", ctx.fast_model, SearchPlan).ainvoke(
            [
                SystemMessage(prompts.render("plan_queries", max_queries=ctx.max_search_queries,
                                             today=date.today().isoformat())),
                HumanMessage(_planner_message(question, known, suggested)),
            ]
        )
    except llm.TRANSIENT_ERRORS:
        raise  # RetryPolicy
    except Exception as exc:  # noqa: BLE001
        logger.warning("[%s] query planning failed: %s", update["trace_id"], exc)
        update["warnings"] = [f"query planning failed, searched the original question ({type(exc).__name__})"]
        update["step_state"] = reporter.report(
            "plan", "failed", f"Failed ({type(exc).__name__}) - searching the question as-is", fallback,
            duration_s=time.time() - started,
        )
        return update

    # Planner first; upstream suggestions fill any remaining slots.
    queries = _dedupe([*plan.queries, *suggested])[: ctx.max_search_queries] or fallback
    freshness = params.freshness or (None if plan.freshness == "none" else plan.freshness)

    update.update(queries=queries, effective_freshness=freshness,
                  llm=LLMInfo(planner_model=ctx.fast_model).model_dump())
    window = f", past {freshness}" if freshness else ""
    update["step_state"] = reporter.report(
        "plan", "done", f"{plural(len(queries), 'query', 'queries')} by {ctx.fast_model}{window}{upstream}", queries,
        duration_s=time.time() - started,
    )
    return update
