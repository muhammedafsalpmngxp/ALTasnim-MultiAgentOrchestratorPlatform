"""How the orchestrator talks to one agent: one agent *thread* per plan step.

Both transports have the same semantics as a LangGraph Agent Server:
- a thread id identifies one execution of one step (stable, so retries are idempotent),
- a run can stop at an ``interrupt()`` and is continued with ``Command(resume=...)``.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel


class AgentRunStatus(BaseModel):
    state: Literal["new", "interrupted", "incomplete", "done", "error"]
    interrupt: Any | None = None
    output: dict[str, Any] | None = None
    error: str | None = None


class AgentClient(Protocol):
    async def status(self, thread_id: str) -> AgentRunStatus: ...

    async def start(self, thread_id: str, agent_input: dict, context: dict) -> None: ...

    async def resume(self, thread_id: str, value: Any, context: dict) -> None: ...

    async def continue_run(self, thread_id: str, context: dict) -> None: ...
