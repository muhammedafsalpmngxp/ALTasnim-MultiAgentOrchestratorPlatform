"""Custom platform routes on the orchestrator deployment (langgraph.json -> http.app).

Runs, threads, streaming, approvals and crons use the built-in Agent Server API.
Only platform-specific views live here.
"""

from __future__ import annotations

from fastapi import FastAPI

from orchestrator_agent.deps import default_deps

app = FastAPI(title="orchestrator platform routes")


@app.get("/platform/agents")
def agents() -> dict:
    """Agents the supervisor can currently plan with (healthy + enabled)."""
    return {name: card.model_dump() for name, card in default_deps().registry.cards().items()}


@app.get("/platform/policies")
def policies() -> dict:
    return default_deps().policies.model_dump()
