"""The verifier's settings (backend/.env, section verifier_agent). Read on use, so tests and the admin can change them.

    VERIFIER_LLM_MODEL=openai:gpt-4o-mini   # <provider>:<model> (a bare name = openai:<name>; key: OPENAI_API_KEY).
                                            # Empty = rule checks only, with a warning on every verdict.

Everything else is fixed here: one setting is all an operator needs.
"""

from __future__ import annotations

import os

LLM_TIMEOUT_SECONDS = 60.0
LLM_MAX_RETRIES = 2
MAX_ANSWER_CHARS = 12000  # of the answer the judge reads
MAX_REQUEST_CHARS = 4000
CALL_LOG_SIZE = 50  # verdicts kept for GET /verify/calls (verifier-ui)


def model_name() -> str | None:
    """``provider:model`` from VERIFIER_LLM_MODEL (``openai:`` added to a bare model name), or None."""
    name = os.getenv("VERIFIER_LLM_MODEL", "").strip().strip('"').strip("'")
    if not name:
        return None
    return name if ":" in name else f"openai:{name}"
