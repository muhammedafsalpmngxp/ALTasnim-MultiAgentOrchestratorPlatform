"""Per-request context (LangGraph ``context_schema``).

Passed on every run: ``graph.invoke(input, config, context={...})`` or via the
SDK ``client.runs.wait(..., context={...})``. Available in nodes as
``runtime.context``. Not stored in state, so tenant data never leaks into
checkpoints.
"""

from __future__ import annotations

from typing import TypedDict


class RequestContext(TypedDict, total=False):
    tenant_id: str
    user_id: str
    roles: list[str]
    locale: str  # "en" | "ar"


def ctx_or_default(ctx: RequestContext | None) -> RequestContext:
    """``runtime.context`` is None when a caller passes no context."""
    base: RequestContext = {"tenant_id": "dev", "user_id": "dev-user", "roles": ["admin"], "locale": "en"}
    return {**base, **(ctx or {})}
