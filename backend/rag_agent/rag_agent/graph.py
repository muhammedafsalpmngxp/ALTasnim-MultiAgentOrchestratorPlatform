"""rag_agent as a LangGraph graph, the platform's agent contract: {"task": AgentTask} in, {"result": {...}} out.

`langgraph dev` serves it together with the HTTP routes of main.py (langgraph.json), and the supervisor runs it
as its ``rag`` node. The question is ``task.params.question`` (else the task objective); the result is what
POST /retrieve returns (question, chunks) with status (failed = no passage matched) and summary. Nothing is
passed to RAG_NEXT_AGENTS: the supervisor routes the result.
"""

import logging
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from rag_agent.config import settings
from rag_agent.main import RetrieveRequest, retrieve_result

log = logging.getLogger("rag_agent")


class RagInput(TypedDict):
    task: dict[str, Any]


class RagOutput(TypedDict):
    result: dict[str, Any]


class RagState(RagInput, RagOutput, total=False):
    pass


def retrieve(state: RagState) -> dict:
    task = state.get("task") or {}
    params = task.get("params") or {}
    question = str(params.get("question") or task.get("objective") or "").strip()
    if not question:
        return {"result": {"status": "failed", "summary": "No question to search the documents for", "chunks": []}}
    try:
        req = RetrieveRequest(question=question, top_k=params.get("top_k") or settings.top_k)
        return {"result": retrieve_result(req, forward=False)}
    except Exception as exc:  # noqa: BLE001 - document store down, model error: a failed step, not a crashed run
        log.exception("retrieve failed")
        return {"result": {"status": "failed", "summary": f"Document search failed: {type(exc).__name__}: {exc}",
                           "question": question, "chunks": []}}


builder = StateGraph(RagState, input_schema=RagInput, output_schema=RagOutput)
builder.add_node("retrieve", retrieve)
builder.add_edge(START, "retrieve")
builder.add_edge("retrieve", END)
graph = builder.compile(name="rag")
