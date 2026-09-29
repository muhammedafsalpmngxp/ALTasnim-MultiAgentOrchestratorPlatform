"""Recent agent outputs, for the UI's /custom/history and /custom/sources.

Kept in-process (fine for `langgraph dev` and a single server). The finalize node also writes each run to the
LangGraph store when the server provides one, which is what a multi-worker deployment should read instead.
"""

from collections import OrderedDict
from threading import Lock

from web_search_agent.settings import get_settings

STORE_NAMESPACE = ("web_search_agent", "history")

_runs: "OrderedDict[str, dict]" = OrderedDict()
_lock = Lock()


def record(output: dict) -> None:
    with _lock:
        _runs[output["trace_id"]] = output
        _runs.move_to_end(output["trace_id"])
        while len(_runs) > get_settings().history_size:
            _runs.popitem(last=False)


def summary(output: dict) -> dict:
    return {
        "trace_id": output["trace_id"],
        "query": output["query"],
        "status": output["status"],
        "created_at": output["created_at"],
        "source_agent": output.get("source_agent"),
        "sources": len(output.get("sources", [])),
        "total_s": output.get("timings", {}).get("total_s"),
        "preview": " ".join((output.get("findings") or [{}])[0].get("content", "").split())[:160],
    }


def recent(limit: int) -> list[dict]:
    with _lock:
        return [summary(run) for run in reversed(list(_runs.values())[-limit:])]


def get(trace_id: str) -> dict | None:
    with _lock:
        return _runs.get(trace_id)


def clear() -> None:
    with _lock:
        _runs.clear()
