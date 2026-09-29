"""Custom routes served on the agent's own port (langgraph.json -> http.app).

- GET  /card                  : used by the orchestrator registry to discover this agent.
- /custom/*                   : for this agent's Angular MFE (frontend/agents/web_search_ui, via /api/agents/web-search)
    POST /custom/search/stream   run the graph once and stream the processing flow (SSE: steps, step..., result)
    GET  /custom/history         recent runs (from the orchestrator and the UI)
    GET  /custom/sources         evidence and sources of one run (?trace_id=), or the configured providers
    POST /custom/retry           "Retry": send a run's output to the output agents again - no search, no LLM
                                 (?trace_id=)
    GET  /custom/health          providers, reranker, LLM, the output routes found on the network

The orchestrator itself uses the standard LangGraph API (threads / runs) with ``{"task": AgentTask}``.
"""

# No `from __future__ import annotations` here: langgraph loads this file by path, and FastAPI must resolve
# SearchRequest at import time to build the OpenAPI spec.

import asyncio
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from utils import AgentTask
from web_search_agent import __version__, llm
from web_search_agent.card import CARD
from web_search_agent.graph import graph
from web_search_agent.nodes.finalize import run_details, step_result
from web_search_agent.nodes.send_output import apply_delivery, deliver_output, publish
from web_search_agent.schemas import Freshness
from web_search_agent.services import checkpoints, handoff, history
from web_search_agent.services.resources import providers_status, reranker
from web_search_agent.settings import get_settings
from web_search_agent.steps import StepReporter

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Load the cross-encoder in the background so the first live search does not wait for it.
    settings = get_settings()
    preload = None
    if settings.reranker_preload and not settings.offline:
        preload = asyncio.create_task(asyncio.to_thread(reranker().load))
    # Look for the output routes on the network now, not on the first search.
    discovery = asyncio.create_task(_find_routes()) if settings.output_paths else None
    yield
    for task in (preload, discovery):
        if task:
            task.cancel()


async def _find_routes() -> None:
    try:
        logger.info("output will be sent to %s", ", ".join(await handoff.endpoints()))
    except Exception as exc:  # noqa: BLE001 - searched again on the first run
        logger.warning("output routes not found yet: %s", exc)


app = FastAPI(title="web_search agent custom routes", version=__version__, lifespan=lifespan)


class SearchRequest(BaseModel):
    """The UI's search form: the supervisor's params (card.WebSearchParams) + top_k (context.Context)."""

    query: str = Field(..., min_length=2, max_length=500)
    top_k: int = Field(5, ge=1, le=20)
    freshness: Freshness | None = None
    include_domains: list[str] = Field(default_factory=list)
    exclude_domains: list[str] = Field(default_factory=list)
    trace_id: str = Field(default_factory=lambda: uuid.uuid4().hex)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@app.get("/card")
def card() -> dict:
    return CARD.model_dump()


@app.post("/custom/search/stream")
async def search_stream(body: SearchRequest) -> StreamingResponse:
    params = body.model_dump(include={"freshness", "include_domains", "exclude_domains"}, exclude_none=True)
    task = AgentTask(task_id=f"ui-{body.trace_id[:8]}", objective=body.query, params=params)
    context = {"source_agent": "web-search-ui", "trace_id": body.trace_id, "top_k": body.top_k}

    async def events():
        try:
            async for chunk in graph.astream({"task": task.model_dump()}, context=context, stream_mode="custom"):
                if chunk.get("type") not in ("steps", "step", "result"):
                    continue
                yield _sse(chunk["type"], chunk.get("result") or chunk.get("step") or {"steps": chunk.get("steps")})
        except Exception as exc:  # noqa: BLE001 - tell the UI instead of cutting the stream
            logger.exception("[%s] run failed", body.trace_id)
            yield _sse("error", {"trace_id": body.trace_id, "error": f"{type(exc).__name__}: {exc}"[:500]})

    return StreamingResponse(
        events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@app.get("/custom/history")
async def get_history(limit: Annotated[int, Query(ge=1, le=100)] = 20) -> list[dict]:
    return history.recent(limit)


@app.get("/custom/sources")
async def get_sources(trace_id: str | None = None) -> dict:
    if trace_id is None:
        return {"providers": providers_status(), "offline": get_settings().offline}
    run = history.get(trace_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"No run with trace_id {trace_id} in recent history")
    keys = ("trace_id", "question", "findings", "evidence", "citations", "sources", "handoffs", "verification",
            "created_at", "retries", "retried_at")
    return {k: run.get(k) for k in keys}


@app.post("/custom/retry")
async def retry(trace_id: Annotated[str, Query(min_length=1, max_length=100)]) -> dict:
    """ "Retry": send another request to the output agents with the saved run. Rebuilds the top N contents (a changed
    WEB_SEARCH_RESULT_TOP_N applies) and sends them - no search, no page fetching, no reranking, no LLM call."""
    saved = await asyncio.to_thread(checkpoints.load, trace_id)
    if not saved or "state" not in saved:
        raise HTTPException(status_code=404, detail=f"No saved run for trace_id {trace_id}")
    state = saved["state"]
    started = time.time()
    result = step_result(state["query"], state.get("evidence") or [], get_settings().result_top_n)
    details = saved.get("details") or history.get(trace_id) or run_details(state, result, state.get("source_agent")
                                                                            or "orchestrator")
    delivered = await deliver_output(state["task"]["task_id"], result, trace_id, StepReporter(None))
    details = apply_delivery({**details, **result}, delivered)
    details["retries"] = int(details.get("retries") or 0) + 1
    details["retried_at"] = datetime.now(UTC).isoformat()
    details["retry_s"] = round(time.time() - started, 2)
    await publish(details)
    return details


@app.get("/custom/health")
async def health() -> dict:
    settings = get_settings()
    model = reranker()
    return {
        "status": "ok",
        "agent": settings.agent_id,
        "version": __version__,
        "offline": settings.offline,
        "providers": providers_status(),
        "reranker": {"model": model.model_name, "loaded": model.loaded, "error": model.load_error},
        "llm": {
            "configured": llm.is_configured(),
            "fast_model": settings.openai_fast_model,
        },
        "output": {
            "paths": settings.output_paths,  # WEB_SEARCH_VERIFIER_PATH
            "ports": settings.output_ports,
            **(await handoff.reachable() if settings.output_paths else {"urls": [], "error": None}),
        },
        "saved_runs": str(checkpoints.directory()),  # for Retry
    }
