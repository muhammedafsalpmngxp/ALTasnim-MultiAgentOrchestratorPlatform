"""transport=local: run an agent graph in-process (development and tests only).

The agent gets its own InMemorySaver, like its own deployment would have its
own Postgres database. Runs execute in an empty ``contextvars.Context`` so the
agent graph is NOT treated as a subgraph of the orchestrator: its checkpoints
and interrupts stay separate, exactly as with a remote Agent Server.
"""

from __future__ import annotations

import asyncio
import contextvars
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from orchestrator_agent.clients.base import AgentRunStatus


class LocalAgentClient:
    def __init__(self, graph: Any):
        self._graph = graph.copy(update={"checkpointer": InMemorySaver()})
        self._errors: dict[str, str] = {}

    @staticmethod
    def _config(thread_id: str) -> dict:
        return {"configurable": {"thread_id": thread_id}}

    async def _run(self, thread_id: str, graph_input: Any, context: dict) -> None:
        coro = self._graph.ainvoke(graph_input, self._config(thread_id), context=context)
        try:
            await asyncio.create_task(coro, context=contextvars.Context())
        except Exception as exc:  # noqa: BLE001 - surfaced as a failed step
            self._errors[thread_id] = f"{type(exc).__name__}: {exc}"

    async def status(self, thread_id: str) -> AgentRunStatus:
        if thread_id in self._errors:
            return AgentRunStatus(state="error", error=self._errors[thread_id])
        snap = await self._graph.aget_state(self._config(thread_id))
        if snap.interrupts:
            return AgentRunStatus(state="interrupted", interrupt=snap.interrupts[0].value)
        if not snap.values:
            return AgentRunStatus(state="new")
        if snap.next:
            return AgentRunStatus(state="incomplete")
        return AgentRunStatus(state="done", output=snap.values.get("result", {}))

    async def start(self, thread_id: str, agent_input: dict, context: dict) -> None:
        await self._run(thread_id, agent_input, context)

    async def resume(self, thread_id: str, value: Any, context: dict) -> None:
        await self._run(thread_id, Command(resume=value), context)

    async def continue_run(self, thread_id: str, context: dict) -> None:
        await self._run(thread_id, None, context)
