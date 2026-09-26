"""transport=remote: call an agent's LangGraph Agent Server deployment with langgraph_sdk.

One remote thread per plan step (stable thread id), runs started with
``multitask_strategy="reject"`` so a duplicate start can never run the agent twice.
"""

from __future__ import annotations

import os
from typing import Any

from langgraph_sdk import get_client

from orchestrator_agent.clients.base import AgentRunStatus


def _is_not_found(exc: Exception) -> bool:
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return status == 404 or type(exc).__name__ == "NotFoundError"


def _first_interrupt_value(thread: dict) -> Any:
    interrupts = thread.get("interrupts") or {}
    for items in interrupts.values():
        for item in items or []:
            return item.get("value") if isinstance(item, dict) else item
    return None


class RemoteAgentClient:
    def __init__(self, url: str, graph_id: str):
        token = os.getenv("ORCHESTRATOR_SERVICE_TOKEN")
        headers = {"Authorization": f"Bearer {token}"} if token else None
        self._client = get_client(url=url, headers=headers)
        self._graph_id = graph_id

    async def status(self, thread_id: str) -> AgentRunStatus:
        try:
            thread = await self._client.threads.get(thread_id)
        except Exception as exc:
            if _is_not_found(exc):
                return AgentRunStatus(state="new")
            raise

        if thread["status"] == "busy":  # a run is still going (e.g. orchestrator restarted): wait for it
            runs = await self._client.runs.list(thread_id, limit=1)
            if runs:
                await self._client.runs.join(thread_id, runs[0]["run_id"])
            thread = await self._client.threads.get(thread_id)

        values = thread.get("values") or {}
        if thread["status"] == "interrupted":
            return AgentRunStatus(state="interrupted", interrupt=_first_interrupt_value(thread))
        if thread["status"] == "error":
            return AgentRunStatus(state="error", error="agent run failed (see agent deployment logs / LangSmith)")
        if not values:
            return AgentRunStatus(state="new")
        return AgentRunStatus(state="done", output=values.get("result", {}))

    async def _wait(self, thread_id: str, context: dict, **kwargs: Any) -> None:
        await self._client.threads.create(thread_id=thread_id, if_exists="do_nothing", graph_id=self._graph_id)
        await self._client.runs.wait(
            thread_id,
            self._graph_id,
            context=context,
            multitask_strategy="reject",
            raise_error=False,
            **kwargs,
        )

    async def start(self, thread_id: str, agent_input: dict, context: dict) -> None:
        await self._wait(thread_id, context, input=agent_input)

    async def resume(self, thread_id: str, value: Any, context: dict) -> None:
        await self._wait(thread_id, context, command={"resume": value})

    async def continue_run(self, thread_id: str, context: dict) -> None:
        await self._wait(thread_id, context, input=None)
