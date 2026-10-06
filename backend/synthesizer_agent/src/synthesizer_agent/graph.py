"""The synthesizer as a LangGraph graph, the platform's agent contract: {"task": AgentTask} in, {"result": {...}} out.

`langgraph dev` serves it with the HTTP routes (server.py, langgraph.json), and the supervisor runs it as its
``synthesizer`` node. The question is ``task.params.question`` (else the task objective); the inputs are the
outputs of the earlier steps (``task.inputs``, e.g. the rag passages and the verifier's verdict). Every call is
listed in GET /runs, like the HTTP calls.
"""

from __future__ import annotations

import time
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from synthesizer_agent.agent import answer, build_prompt, llm_info
from synthesizer_agent.runs import runs


class SynthesizerInput(TypedDict):
    task: dict[str, Any]


class SynthesizerOutput(TypedDict):
    result: dict[str, Any]


class SynthesizerState(SynthesizerInput, SynthesizerOutput, total=False):
    pass


def synthesize(state: SynthesizerState) -> dict:
    task = state["task"]
    question = (task.get("params") or {}).get("question") or task.get("objective")
    inputs = task.get("inputs") or {}
    llm = llm_info()
    prompt = build_prompt(question, inputs) if llm and inputs else None
    run_id = runs.start(question, inputs, llm, prompt, endpoint="graph synthesizer (supervisor)")
    started = time.perf_counter()
    try:
        result = answer(question, inputs)
    except Exception as exc:  # LLM unreachable, wrong key, ... -> the supervisor sees a failed step
        runs.fail(run_id, f"{type(exc).__name__}: {exc}", time.perf_counter() - started)
        raise
    runs.finish(run_id, result, time.perf_counter() - started)
    return {"result": result}


builder = StateGraph(SynthesizerState, input_schema=SynthesizerInput, output_schema=SynthesizerOutput)
builder.add_node("synthesize", synthesize)
builder.add_edge(START, "synthesize")
builder.add_edge("synthesize", END)
graph = builder.compile(name="synthesizer")
