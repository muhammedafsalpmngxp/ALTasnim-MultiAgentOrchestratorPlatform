"""Sync twins for the async nodes.

The Agent Server and the orchestrator run this graph with the async API (``ainvoke`` / ``astream``). The
platform's contract helper (``utils.testing.run_agent_graph``) and scripts use the sync ``graph.invoke``: there each
node's coroutine runs on one long-lived background event loop, so per-loop resources (httpx clients, semaphores
in ``services/resources.py``) stay valid across runs. ``run_coroutine_threadsafe`` carries the caller's
contextvars over, so ``get_runtime()`` and ``get_stream_writer()`` work in both modes.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.runnables import RunnableLambda

_loop: asyncio.AbstractEventLoop | None = None
_lock = threading.Lock()


def _background_loop() -> asyncio.AbstractEventLoop:
    global _loop
    with _lock:
        if _loop is None:
            _loop = asyncio.new_event_loop()
            threading.Thread(target=_loop.run_forever, name="web-search-sync-nodes", daemon=True).start()
        return _loop


def dual(node: Callable[[Any], Awaitable[dict]]) -> RunnableLambda:
    """An async node that can also be invoked from the sync graph API."""

    def run_sync(arg: Any) -> dict:
        return asyncio.run_coroutine_threadsafe(node(arg), _background_loop()).result()

    return RunnableLambda(run_sync, afunc=node, name=node.__name__)
