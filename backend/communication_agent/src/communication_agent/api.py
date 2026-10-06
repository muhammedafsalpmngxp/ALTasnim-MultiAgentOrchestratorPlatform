"""Custom routes on the agent's own port (langgraph.json -> http.app), used by communication-ui."""

from __future__ import annotations

from fastapi import FastAPI

from communication_agent.card import CARD
from communication_agent.channels.email import SENT
from communication_agent.settings import get_settings

app = FastAPI(title="communication agent custom routes")


@app.get("/card")
def card() -> dict:
    return CARD.model_dump()


@app.get("/custom/status")
def status() -> dict:
    """How email is configured (EMAIL_DELIVERY, SMTP_*, COMMUNICATION_LLM_MODEL); never the password."""
    return get_settings().public()


@app.get("/custom/sent")
def sent() -> list[dict]:
    """The emails sent (or logged) since the agent started, newest first (at most 50); no bodies."""
    return list(SENT)
