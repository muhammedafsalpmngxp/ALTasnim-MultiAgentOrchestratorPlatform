"""Custom routes on the agent's own port (langgraph.json -> http.app)."""

from __future__ import annotations

from fastapi import FastAPI

from communication_agent.card import CARD

app = FastAPI(title="communication agent custom routes")


@app.get("/card")
def card() -> dict:
    return CARD.model_dump()


@app.get("/custom/templates")
def templates() -> dict:
    # TODO(team-comms): email templates managed from communication-ui.
    return {"templates": []}
