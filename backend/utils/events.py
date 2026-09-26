"""Standard custom stream events (``stream_mode="custom"``).

Nodes emit them with ``get_stream_writer()``. The Angular Runs MFE renders them.
The schema is also exported to contracts/events/run-event.schema.json.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from langgraph.config import get_stream_writer


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def emit(event_type: str, **data: Any) -> None:
    """Emit a custom event. Does nothing when not streaming in ``custom`` mode."""
    try:
        writer = get_stream_writer()
    except RuntimeError:  # called outside a graph run (e.g. unit tests)
        return
    writer({"type": event_type, "at": now_iso(), **data})
