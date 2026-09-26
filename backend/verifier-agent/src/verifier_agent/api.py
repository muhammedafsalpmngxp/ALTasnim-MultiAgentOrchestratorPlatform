"""Custom routes on the agent's own port (langgraph.json -> http.app)."""

from __future__ import annotations

from fastapi import FastAPI

from verifier_agent.card import CARD

app = FastAPI(title="verifier agent custom routes")


@app.get("/card")
def card() -> dict:
    return CARD.model_dump()
