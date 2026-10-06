"""Remembers the most recent requests so the UI can show them. Memory only: empty after a restart."""

from __future__ import annotations

import copy
import os
import threading
import uuid
from collections import deque
from datetime import UTC, datetime
from typing import Any


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class RunStore:
    def __init__(self, max_runs: int):
        self._runs: deque[dict] = deque(maxlen=max_runs)
        self._lock = threading.Lock()  # requests are handled in parallel threads

    def start(self, question: str | None, inputs: dict[str, Any], llm: dict | None, prompt: str | None,
              endpoint: str = "POST /synthesize") -> str:
        run = {"id": uuid.uuid4().hex[:12], "state": "running", "received_at": _now(), "finished_at": None,
               "seconds": None, "endpoint": endpoint, "question": question, "inputs": inputs, "llm": llm,
               "prompt": prompt, "result": None, "error": None}
        with self._lock:
            self._runs.appendleft(run)  # newest first
        return run["id"]

    def finish(self, run_id: str, result: dict, seconds: float) -> None:
        self._update(run_id, state="done", result=result, seconds=round(seconds, 1))

    def fail(self, run_id: str, error: str, seconds: float) -> None:
        self._update(run_id, state="error", error=error, seconds=round(seconds, 1))

    def list(self) -> list[dict]:
        """Newest first, without the prompt (it can be long). GET /runs/{id} has it."""
        with self._lock:
            return [{k: copy.deepcopy(v) for k, v in run.items() if k != "prompt"} for run in self._runs]

    def get(self, run_id: str) -> dict | None:
        with self._lock:
            run = next((r for r in self._runs if r["id"] == run_id), None)
            return copy.deepcopy(run) if run else None

    def clear(self) -> None:
        with self._lock:
            self._runs.clear()

    def _update(self, run_id: str, **changes) -> None:
        with self._lock:
            for run in self._runs:
                if run["id"] == run_id:
                    run.update(changes, finished_at=_now())
                    return


runs = RunStore(int(os.getenv("SYNTHESIZER_MAX_RUNS", "50")))
