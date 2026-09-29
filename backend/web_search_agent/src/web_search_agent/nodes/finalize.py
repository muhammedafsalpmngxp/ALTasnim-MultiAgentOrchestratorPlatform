"""Build the step ``result`` (the agent's output) and the full run details for this agent's UI.

``result`` (graph output, see ``card.WebSearchResult``) goes to the verifier (``task.inputs[<step id>]``) and to any
later step. It carries only the input ``question`` and the top ``WEB_SEARCH_RESULT_TOP_N`` (3) contents, plus the
platform's required ``status`` (ok/failed drives replanning) and ``summary`` (chat reply, emails). ``findings`` and
``sources`` (URL strings) are the names the verifier checks.

The full run (all ranked evidence, citations, flow, timings) goes to send_output, which sends the result to
the verifier / synthesizer (if selected), then streams the details to the UI and keeps them in the UI history.
"""

from __future__ import annotations

import time

from langgraph.runtime import get_runtime

from web_search_agent.context import Context, resolve
from web_search_agent.schemas import LLMInfo
from web_search_agent.settings import get_settings
from web_search_agent.state import State
from web_search_agent.steps import ordered_steps, timings


def top_contents(evidence: list[dict], n: int) -> list[dict]:
    """The best ``n`` passages, from ``n`` different pages where possible (the best passage of each page first)."""
    seen: set[str] = set()
    distinct = [e for e in evidence if not (e["url"] in seen or seen.add(e["url"]))]
    chosen = distinct[:n]
    chosen += [e for e in evidence if e not in chosen][: n - len(chosen)]
    chosen.sort(key=evidence.index)  # keep the reranker's order
    return [
        {"rank": rank, "title": e["title"], "url": e["url"], "content": " ".join(e["content"].split())}
        for rank, e in enumerate(chosen, start=1)
    ]


def summary_text(question: str, contents: list[dict]) -> str:
    """The question and the top contents as one readable text."""
    if not contents:
        return f"No web results for: {question}"
    blocks = "\n\n".join(f"[{c['rank']}] {c['title']} - {c['url']}\n{c['content']}" for c in contents)
    return f"Question: {question}\n\nTop {len(contents)} web results:\n\n{blocks}"


def step_result(question: str, evidence: list[dict], n: int) -> dict:
    contents = top_contents(evidence, n)
    return {
        "status": "ok" if contents else "failed",
        "summary": summary_text(question, contents),
        "question": question,
        "findings": contents,
        "sources": [c["url"] for c in contents],
    }


def run_details(state: dict, result: dict, source_agent: str) -> dict:
    """Everything this run produced, for the UI stream, /custom/history and /custom/sources (send_output adds the
    responses of the agents it was sent to). Also used by "Retry" to rebuild a run from its saved state."""
    question = state["query"]
    return {
        **result,
        "citations": state.get("sources") or [],
        "evidence": state.get("evidence") or [],
        "context": state.get("context") or "",
        "query": question,
        "search_queries": state.get("queries") or [question],
        "provider_used": state.get("provider_used"),
        "reranker": state.get("reranker") or "not run",
        "llm": state.get("llm") or LLMInfo().model_dump(),
        "steps": ordered_steps(state.get("step_state") or {}),
        "timings": timings(state.get("step_state") or {}, time.time() - state["started_at"]),
        "warnings": state.get("warnings") or [],
        "trace_id": state["trace_id"],
        "source_agent": source_agent,
        "created_at": state["created_at"],
    }


async def finalize(state: State) -> dict:
    ctx = resolve(get_runtime(Context))
    result = step_result(state["query"], state.get("evidence", []), get_settings().result_top_n)
    return {"result": result, "details": run_details(state, result, ctx.source_agent)}
