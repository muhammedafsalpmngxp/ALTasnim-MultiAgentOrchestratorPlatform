"""Custom routes served on the agent's own port (langgraph.json -> http.app).

- GET /card        : used by the orchestrator registry to discover this agent.
- /custom/*        : management endpoints for this agent's Angular MFE (web-search-ui).
"""

from __future__ import annotations

from fastapi import FastAPI

from web_search_agent.card import CARD

app = FastAPI(title="web_search agent custom routes")


@app.get("/card")
def card() -> dict:
    return CARD.model_dump()


@app.get("/custom/sources")
def sources() -> dict:
    # TODO(team-search): return configured providers / allowed domains for the UI.
    return {"provider": "sample", "allowed_domains": []}
