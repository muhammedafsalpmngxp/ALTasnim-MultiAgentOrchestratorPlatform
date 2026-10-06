"""Synthesizer agent API (plain FastAPI). Receives ANY request and answers it.

Start (from backend/synthesizer_agent):  uvicorn synthesizer_agent.api:app --app-dir src --host 0.0.0.0 --port 8203
Docs:                                     http://localhost:8203/docs

Send anything with POST / PUT / PATCH to any path (/synthesize, /verify, /, ...): JSON object, list or plain text.
The question is taken from a field like "question", "query", "q" or "prompt"; without one, the LLM works it out.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware

from synthesizer_agent.agent import answer, build_prompt, llm_info, split_request
from synthesizer_agent.card import CARD
from synthesizer_agent.runs import runs

app = FastAPI(title="Synthesizer agent", description="Receives any request and answers it from the data it contains.")

# The micro-frontend (synthesizer-ui :4304, or the team shell :4200) calls this API from the browser
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv(
        "SYNTHESIZER_CORS_ORIGINS", "http://localhost:4200,http://localhost:4304").split(",") if o.strip()],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["*"],
)

_EXAMPLE = {
    "question": "What is the price of iPhone 16 in Oman?",
    "chunks": ["Apple Oman: iPhone 16 from OMR 329", "Lulu Oman: iPhone 16 128GB OMR 319"],
}


async def _read_body(request: Request) -> Any:
    """JSON if the body is JSON, else the plain text."""
    text = (await request.body()).decode("utf-8", errors="replace")
    if not text.strip():
        return None
    try:
        return json.loads(text)
    except ValueError:
        return text


async def _handle(request: Request) -> dict:
    question, inputs = split_request(await _read_body(request))
    llm = llm_info()
    prompt = build_prompt(question, inputs) if llm and inputs else None
    run_id = runs.start(question, inputs, llm, prompt, endpoint=f"{request.method} {request.url.path}")
    started = time.perf_counter()
    try:
        # the LLM call is blocking, so run it off the event loop
        result = await run_in_threadpool(answer, question, inputs)
    except Exception as exc:  # LLM unreachable, wrong key, ...
        error = f"{type(exc).__name__}: {exc}"
        runs.fail(run_id, error, time.perf_counter() - started)
        raise HTTPException(status_code=502, detail=f"LLM call failed: {error}") from exc
    runs.finish(run_id, result, time.perf_counter() - started)
    return result


@app.get("/ok")
def ok() -> dict:
    return {"ok": True}


@app.get("/card")
def card() -> dict:
    return {**CARD, "llm": llm_info()}


@app.post("/synthesize", openapi_extra={"requestBody": {"content": {"application/json": {"example": _EXAMPLE}}}})
async def synthesize(request: Request) -> dict:
    """Any JSON or text. Same as sending to any other path."""
    return await _handle(request)


@app.get("/runs")
def list_runs() -> list[dict]:
    """Recent requests, newest first (for the UI)."""
    return runs.list()


@app.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    """One request, including the prompt sent to the LLM."""
    run = runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@app.delete("/runs")
def clear_runs() -> dict:
    runs.clear()
    return {"status": "cleared"}


# ---- catch-all: keep these LAST so they never hide the routes above ----

@app.api_route("/{path:path}", methods=["POST", "PUT", "PATCH"], include_in_schema=False)
async def receive_anything(request: Request) -> dict:
    return await _handle(request)


@app.get("/{path:path}", include_in_schema=False)
def any_get(path: str) -> dict:
    return {"ok": True, "agent": "synthesizer", "path": f"/{path}",
            "hint": "Send any data here with POST and the synthesizer answers it"}
