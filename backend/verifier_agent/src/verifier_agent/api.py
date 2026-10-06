"""Custom routes on the agent's own port (langgraph.json -> http.app).

Only the supervisor runs the verifier (LangGraph API, /threads/{id}/runs). These routes describe it and list its
last verdicts for verifier-ui.
"""

from __future__ import annotations

from fastapi import FastAPI

from verifier_agent import calls, settings
from verifier_agent.card import CARD

app = FastAPI(title="verifier agent custom routes")


@app.get("/card")
def card() -> dict:
    return CARD.model_dump()


@app.get("/verify/status")
def status() -> dict:
    """What the verifier checks with: the judge's model, or rule checks only."""
    return {"model": settings.model_name(), "mode": "llm" if settings.model_name() else "rules only"}


@app.get("/verify/calls")
def verify_calls() -> list[dict]:
    return list(calls.CALLS)


@app.delete("/verify/calls")
def clear_verify_calls() -> dict:
    calls.CALLS.clear()
    return {"cleared": True}
