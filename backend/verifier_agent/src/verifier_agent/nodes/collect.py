"""collect: the task -> the question and the answer. No LLM.

The question is ``params.request``, else the question an input carries, else the task objective. The answer is the
input ``params.answer_step``, else the last input that has an ``answer``, else the only input. Nothing else is read.
"""

from __future__ import annotations

import time

from utils import AgentTask
from verifier_agent.card import VerifyParams
from verifier_agent.state import State
from verifier_agent.text import text_of


def _request(params: VerifyParams, task: AgentTask) -> str:
    if params.request and params.request.strip():
        return params.request.strip()
    for out in task.inputs.values():
        if isinstance(out, dict) and str(out.get("question") or "").strip():
            return str(out["question"]).strip()
    return task.objective


def _answer_step(params: VerifyParams, task: AgentTask) -> str | None:
    if params.answer_step in task.inputs:
        return params.answer_step
    with_answer = [sid for sid, out in task.inputs.items() if isinstance(out, dict) and out.get("answer")]
    if with_answer:
        return with_answer[-1]
    return next(iter(task.inputs)) if len(task.inputs) == 1 else None


def collect(state: State) -> dict:
    task = AgentTask.model_validate(state["task"])
    params = VerifyParams.model_validate({k: v for k, v in task.params.items() if k in VerifyParams.model_fields})
    step = _answer_step(params, task)
    answer = None
    if step is not None:
        out = task.inputs[step]
        answer = {"step": step, "text": text_of(out), "shape": "object" if isinstance(out, dict) else "not_object",
                  "status": str(out["status"]) if isinstance(out, dict) and out.get("status") is not None else None}
    return {"started": time.perf_counter(), "request": _request(params, task), "answer": answer}
