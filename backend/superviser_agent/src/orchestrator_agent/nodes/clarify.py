"""Ask the user a question and wait (``interrupt``). The answer goes back to the supervisor.

Resume with: ``Command(resume="rijin@gmail.com")`` or ``Command(resume={"answer": "..."})``.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage
from langgraph.types import interrupt

from orchestrator_agent.state import OrchestratorState


def clarify(state: OrchestratorState) -> dict:
    question = state.get("pending_question") or "Could you give more details?"
    answer = interrupt({"kind": "clarification", "question": question})
    text = answer.get("answer", "") if isinstance(answer, dict) else str(answer)
    return {
        "clarifications": [*state.get("clarifications", []), text],
        "messages": [HumanMessage(text)],
        "pending_question": None,
    }
