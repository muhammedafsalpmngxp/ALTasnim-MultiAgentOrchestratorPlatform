"""Saved runs for "Retry": what sending the output needs, saved as one JSON file per run by ``send_output``.

``backend/web_search_agent/logs/checkpoints/<trace_id>.json`` (git-ignored; ``WEB_SEARCH_CHECKPOINT_DIR``). "Retry"
(``POST /custom/retry``, the UI buttons) loads it, rebuilds the top N contents and sends another request to the output
agents - no search, no page fetching, no reranking, no LLM call. Survives restarts; the newest
``WEB_SEARCH_CHECKPOINT_KEEP`` are kept. Blocking file I/O: call these through ``asyncio.to_thread``.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

from web_search_agent.settings import get_settings

AGENT_DIR = Path(__file__).resolve().parents[3]  # backend/web_search_agent
# The pipeline state a retry needs (everything up to the reranked evidence).
STATE_KEYS = ("task", "query", "trace_id", "source_agent", "created_at", "started_at", "top_k", "queries",
              "provider_used", "reranker", "evidence", "sources", "context", "llm", "step_state", "warnings")
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")


def directory() -> Path:
    configured = get_settings().checkpoint_dir.strip()
    if configured:
        return Path(configured)
    if "pytest" in sys.modules:  # tests (also the orchestrator's, which run this graph) never write into logs/
        return Path(tempfile.gettempdir()) / "web-search-agent-test-checkpoints"
    return AGENT_DIR / "logs" / "checkpoints"


def _path(trace_id: str) -> Path:
    if not _SAFE_ID.match(trace_id):  # the id becomes a file name: no paths
        raise ValueError(f"invalid trace_id {trace_id!r}")
    return directory() / f"{trace_id}.json"


def save(trace_id: str, data: dict) -> Path:
    folder = directory()
    folder.mkdir(parents=True, exist_ok=True)
    path = _path(trace_id)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")
    tmp.replace(path)  # atomic: a crash never leaves half a checkpoint
    _prune(folder)
    return path


def load(trace_id: str) -> dict | None:
    try:
        path = _path(trace_id)
    except ValueError:
        return None
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def update(trace_id: str, **fields: object) -> None:
    data = load(trace_id)
    if data is not None:
        save(trace_id, {**data, **fields})


def _prune(folder: Path) -> None:
    keep = max(1, get_settings().checkpoint_keep)
    files = sorted(folder.glob("*.json"), key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True)
    for old in files[keep:]:
        old.unlink(missing_ok=True)
