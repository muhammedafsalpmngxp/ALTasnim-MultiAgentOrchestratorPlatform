"""The last verdicts, for GET /verify/calls (verifier-ui). In memory: cleared when the server restarts."""

from __future__ import annotations

import uuid
from collections import deque
from datetime import UTC, datetime

from verifier_agent import settings
from verifier_agent.text import cut

CALLS: deque[dict] = deque(maxlen=settings.CALL_LOG_SIZE)


def record(state: dict, result: dict, seconds: float | None) -> None:
    task = state.get("task") or {}
    answer = state.get("answer") or {}
    CALLS.appendleft({
        "id": str(uuid.uuid4()),
        "received_at": datetime.now(UTC).isoformat(),
        "task_id": task.get("task_id"),
        "question": state.get("request") or "",
        "answer_step": answer.get("step"),
        "answer": cut(answer.get("text") or "", settings.MAX_ANSWER_CHARS),
        "result": result,
        "duration_ms": round(seconds * 1000, 1) if seconds is not None else None,
    })
