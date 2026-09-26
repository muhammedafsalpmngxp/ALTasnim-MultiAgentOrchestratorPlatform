"""Auth helpers used by every deployment's ``auth.py`` (``langgraph_sdk.Auth``).

AUTH_MODE=dev  (default)  : every request is accepted as a dev user with all permissions.
AUTH_MODE=jwt             : TODO(platform): verify the JWT from your identity provider
                            (Entra ID / Keycloak) and map claims -> identity/tenant/permissions.
"""

from __future__ import annotations

import os
from typing import Any

# Permission that only the orchestrator's service token carries.
INVOKE_AGENTS = "agents:invoke"


def resolve_user(authorization: str | None) -> dict[str, Any]:
    mode = os.getenv("AUTH_MODE", "dev")
    if mode == "dev":
        return {
            "identity": "dev-user",
            "tenant": "dev",
            "permissions": [INVOKE_AGENTS, "platform:admin"],
        }
    raise NotImplementedError(
        "AUTH_MODE=jwt is not implemented yet: verify the bearer token here "
        "and return identity, tenant and permissions."
    )
