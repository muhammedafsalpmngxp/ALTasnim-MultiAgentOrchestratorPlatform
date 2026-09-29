"""LangGraph custom auth: only the orchestrator (service permission) may run this agent."""

from __future__ import annotations

from langgraph_sdk import Auth

from utils.auth import INVOKE_AGENTS, resolve_user

auth = Auth()


@auth.authenticate
async def authenticate(authorization: str | None) -> Auth.types.MinimalUserDict:
    return resolve_user(authorization)


@auth.on.threads
async def orchestrator_only(ctx: Auth.types.AuthContext, value: dict) -> None:
    if INVOKE_AGENTS not in ctx.permissions:
        raise Auth.exceptions.HTTPException(status_code=403, detail="Agents are invoked via the orchestrator only")
