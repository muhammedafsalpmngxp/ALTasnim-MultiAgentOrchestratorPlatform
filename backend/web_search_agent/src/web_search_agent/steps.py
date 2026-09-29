"""The processing flow shown in the UI: each node reports its step through the custom stream
(`stream_mode="custom"`) and records it in the state so it is also part of AgentOutput."""

import time
from collections.abc import Callable
from typing import Any

from web_search_agent.schemas import PipelineStep, StepId, StepStatus, Timings

FLOW: list[tuple[StepId, str]] = [
    ("plan", "Query planner"),
    ("search", "Web search"),
    ("extract", "Fetch & extract"),
    ("chunk", "Chunking"),
    ("rerank", "Rerank"),
    ("verify", "Send output"),
]
_TITLES = dict(FLOW)
_TIMING_FIELDS = {"plan": "plan_s", "search": "search_s", "extract": "extract_s", "chunk": "chunk_s",
                  "rerank": "rerank_s"}

Writer = Callable[[Any], None]


def pending_flow() -> list[dict]:
    return [PipelineStep(id=step_id, title=title).model_dump() for step_id, title in FLOW]


def span(start: float) -> dict:
    return {"start": start, "end": time.time()}


def span_seconds(spans: dict, step_id: str) -> float | None:
    value = spans.get(step_id)
    return round(value["end"] - value["start"], 2) if value else None


class StepReporter:
    """`report()` streams the change and returns `{"step_state": {...}}` to merge into the node's update."""

    def __init__(self, writer: Writer | None):
        self._write = writer or (lambda _event: None)

    def announce(self) -> None:
        self._write({"type": "steps", "steps": pending_flow()})

    def report(
        self,
        step_id: StepId,
        status: StepStatus,
        detail: str = "",
        items: list[str] | None = None,
        duration_s: float | None = None,
    ) -> dict:
        step = PipelineStep(
            id=step_id, title=_TITLES[step_id], status=status, detail=detail, items=items or [],
            duration_s=round(duration_s, 2) if duration_s is not None else None,
        ).model_dump()
        self._write({"type": "step", "step": step})
        return {step_id: step}

    def skip(self, step_ids: list[StepId], reason: str) -> dict:
        update: dict = {}
        for step_id in step_ids:
            update.update(self.report(step_id, "skipped", reason))
        return update


def ordered_steps(step_state: dict) -> list[dict]:
    return [step_state.get(step_id) or PipelineStep(id=step_id, title=title).model_dump() for step_id, title in FLOW]


def timings(step_state: dict, total_s: float) -> dict:
    result = Timings(total_s=round(total_s, 2))
    for step_id, field in _TIMING_FIELDS.items():
        duration = (step_state.get(step_id) or {}).get("duration_s")
        if duration is not None:
            setattr(result, field, duration)
    return result.model_dump()


def plural(count: int, word: str, many: str | None = None) -> str:
    return f"{count} {word if count == 1 else many or word + 's'}"
