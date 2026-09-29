"""Custom routes on the agent's own port (langgraph.json -> http.app)."""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import Body, FastAPI, Request
from fastapi.responses import HTMLResponse

from verifier_agent import discovery
from verifier_agent.card import CARD
from verifier_agent.graph import graph

logger = logging.getLogger(__name__)

app = FastAPI(title="verifier agent custom routes")

# Recent /verify calls for the /ui page (in memory: cleared when the container restarts).
CALLS: deque[dict] = deque(maxlen=200)
UI_HTML = Path(__file__).with_name("ui.html")


@app.get("/card")
def card() -> dict:
    return CARD.model_dump()


@app.post("/verify")
async def verify(request: Request, payload: Annotated[dict, Body()]) -> dict:
    """Plain HTTP entry for callers that push results directly (e.g. a web-search agent).

    Accepts either ``{"task": {...AgentTask...}}`` or any JSON object, which is
    verified as the output of a single earlier step named ``web_search``.
    """
    client = request.client.host if request.client else "unknown"
    logger.info("Received /verify call from %s (keys: %s)", client, sorted(payload))
    logger.info("/verify payload: %s", json.dumps(payload, ensure_ascii=False, default=str))
    task = payload.get("task") if isinstance(payload.get("task"), dict) else {
        "task_id": str(uuid.uuid4()),
        "objective": "Verify pushed output",
        "inputs": {("rag" if "chunks" in payload else "web_search"): payload},
    }
    call = {"id": str(uuid.uuid4()), "received_at": datetime.now(UTC).isoformat(),
            "client": client, "question": _question(payload, task), "task": task, "payload": payload}
    CALLS.appendleft(call)
    started = time.perf_counter()
    try:
        out = await graph.ainvoke({"task": task})
    except Exception as exc:
        call["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        call["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
    call["result"] = out["result"]
    logger.info("Answered /verify call from %s: %s", client, out["result"]["summary"])
    synth = await _send_to_synthesizer(call["question"], out["result"], task)
    if synth is not None:
        call["synthesizer"] = synth
        out = {**out, "synthesizer": synth}
    return out


async def _send_to_synthesizer(question: str, result: dict, task: dict) -> dict | None:
    """POST {question, verification, inputs} to the synthesizer found on the LAN (see ``discovery``).

    Sent whether or not verification passed, so the synthesizer can explain either outcome. If the machine
    stops answering, the network is searched again once. A failing synthesizer never loses the verdict:
    the error is returned instead of its reply. ``None`` = forwarding is off (VERIFIER_SYNTHESIZER_PATH empty).
    """
    if not os.getenv("VERIFIER_SYNTHESIZER_URL", "").strip() and discovery.target() is None:
        return None
    url = await discovery.synthesizer_url()
    if url is None:
        port, path = discovery.target()
        return {"url": None, "error": f"No other machine in the local network has port {port} open and serves {path}"}
    body = {"question": question, "verification": result, "inputs": task.get("inputs") or {}}
    timeout = float(os.getenv("VERIFIER_SYNTHESIZER_TIMEOUT_SECONDS", "120"))
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                res = await client.post(url, json=body)
            except httpx.TransportError:  # machine gone or IP changed: find it again and retry once
                new_url = await discovery.synthesizer_url(refresh=True)
                if new_url is None:
                    raise
                url = new_url
                res = await client.post(url, json=body)
        res.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("Sending the verdict to the synthesizer at %s failed: %s", url, exc)
        return {"url": url, "error": str(exc) or type(exc).__name__}
    try:
        reply = res.json()
    except ValueError:
        reply = res.text
    logger.info("Synthesizer at %s answered %s", url, res.status_code)
    return {"url": url, "status": res.status_code, "response": reply}


@app.get("/verify/calls")
def verify_calls() -> list[dict]:
    return list(CALLS)


@app.delete("/verify/calls")
def clear_verify_calls() -> dict:
    CALLS.clear()
    return {"cleared": True}


@app.get("/ui", response_class=HTMLResponse)
def ui() -> str:
    return UI_HTML.read_text(encoding="utf-8")


def _question(payload: dict, task: dict) -> str:
    if payload.get("question"):
        return str(payload["question"])
    for out in (task.get("inputs") or {}).values():
        if isinstance(out, dict) and out.get("question"):
            return str(out["question"])
    return str(task.get("objective", ""))
