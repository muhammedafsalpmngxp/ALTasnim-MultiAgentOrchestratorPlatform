"""The body of every agent node (``web_search``, ``communication``, ``verifier``, ...): runs ONE plan step on
that agent (in-process graph or its own deployment, see config/agents.*.yaml).

- One agent thread per (orchestrator thread, turn, step, attempt): stable id, so a
  re-run of this node never starts the agent twice, while the next question in the
  same chat (a new turn, see intake) gets fresh agent threads instead of the old results.
- If the agent stops at its own ``interrupt()`` (e.g. email approval), this node
  raises an orchestrator ``interrupt()`` with the agent's payload. There is one
  inbox for all approvals, and resuming the orchestrator resumes the agent.
- At most ONE interrupt per execution of this node. If the agent asks again, the
  step is returned as "pending" and ``progress`` dispatches it again. LangGraph
  replays interrupt answers by position within a node, so this avoids giving an
  old answer to a new question.
"""

from __future__ import annotations

import uuid

from langgraph.config import get_config
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from orchestrator_agent.clients import AgentRunStatus
from orchestrator_agent.deps import DepsProvider
from utils import AgentResult, AgentTask, RequestContext, Step, StepStatus
from utils.context import ctx_or_default
from utils.events import emit, now_iso

_NS = uuid.UUID("5b0f2f4e-2c71-4d0e-9a52-6f1f2d8c9a10")


def _status(step: Step, status: str, thread: str, detail: str | None = None) -> dict:
    return {step.id: StepStatus(status=status, agent=step.agent, updated_at=now_iso(),
                                remote_thread=thread, detail=detail).model_dump()}


def _finish(step: Step, st: AgentRunStatus, thread: str) -> dict:
    if st.state == "done":
        output = st.output or {}
        status = output.get("status", "ok")
        status = status if status in ("ok", "failed", "rejected") else "ok"
        result = AgentResult(step_id=step.id, agent=step.agent, status=status, output=output,
                             error=None if status == "ok" else output.get("summary"))
    else:
        result = AgentResult(step_id=step.id, agent=step.agent, status="failed",
                             error=st.error or f"agent ended in state {st.state}")
    ui_status = {"ok": "done", "failed": "failed", "rejected": "rejected"}[result.status]
    emit("step_finished", step_id=step.id, agent=step.agent, status=result.status)
    return {"results": {step.id: result.model_dump()},
            "step_status": _status(step, ui_status, thread, result.error)}


def make_run_agent(get_deps: DepsProvider):
    async def run_agent(payload: dict, runtime: Runtime[RequestContext]) -> dict:
        step = Step.model_validate(payload["step"])
        ctx = dict(ctx_or_default(runtime.context))
        parent = get_config()["configurable"].get("thread_id", "no-thread")
        key = f"{parent}:{payload.get('turn', 0)}:{step.id}:{payload.get('attempt', 0)}"
        thread = str(uuid.uuid5(_NS, key))

        try:
            client = get_deps().registry.client(step.agent)
            st = await client.status(thread)
            if st.state == "new":
                emit("step_started", step_id=step.id, agent=step.agent)
                task = AgentTask(task_id=step.id, objective=step.objective, params=step.params,
                                 inputs=payload.get("deps", {}))
                await client.start(thread, {"task": task.model_dump()}, ctx)
                st = await client.status(thread)
            elif st.state == "incomplete":
                await client.continue_run(thread, ctx)
                st = await client.status(thread)
        except Exception as exc:  # noqa: BLE001 - agent unreachable etc. -> failed step, supervisor replans
            return _finish(step, AgentRunStatus(state="error", error=f"{type(exc).__name__}: {exc}"), thread)

        if st.state != "interrupted":
            return _finish(step, st, thread)

        # The agent is waiting for a human. Pause the orchestrator with the agent's request.
        emit("step_waiting_approval", step_id=step.id, agent=step.agent)
        decision = interrupt({"kind": "agent_approval", "step_id": step.id, "agent": step.agent,
                              "objective": step.objective, "request": st.interrupt})
        try:
            await client.resume(thread, decision, ctx)
            st = await client.status(thread)
        except Exception as exc:  # noqa: BLE001
            return _finish(step, AgentRunStatus(state="error", error=f"{type(exc).__name__}: {exc}"), thread)

        if st.state == "interrupted":  # agent asks again -> progress re-dispatches this step
            pending = AgentResult(step_id=step.id, agent=step.agent, status="pending")
            return {"results": {step.id: pending.model_dump()},
                    "step_status": _status(step, "waiting_approval", thread)}
        return _finish(step, st, thread)

    return run_agent
