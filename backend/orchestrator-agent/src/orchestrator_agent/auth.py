"""LangGraph custom auth for the orchestrator deployment.

Every thread gets an ``owner`` in its metadata, and every read/search is
filtered by it. Users only ever see their own runs and approvals, including
``threads.search(status="interrupted")`` for the Approvals inbox.
TODO(platform): add tenant scoping and an approver role (approvers see their tenant's approvals).
"""

from __future__ import annotations

from langgraph_sdk import Auth

from utils.auth import resolve_user

auth = Auth()


@auth.authenticate
async def authenticate(authorization: str | None) -> Auth.types.MinimalUserDict:
    return resolve_user(authorization)


@auth.on
async def owner_scope(ctx: Auth.types.AuthContext, value: dict) -> dict:
    filters = {"owner": ctx.user.identity}
    metadata = value.setdefault("metadata", {}) if isinstance(value, dict) else {}
    if metadata is not None:
        metadata.update(filters)
    return filters
