"""judge: ONE structured LLM call: does the answer match the question? It reads only the question and the answer.

The prompts are prompts/judge_system.md (how to check) and prompts/judge_input.md (the template). Without
VERIFIER_LLM_MODEL the judge is skipped with a warning (rule checks only); an LLM error is reported in
``judge_error`` and fails the check in ``verdict`` without blaming the answer (never a crash, never a silent pass).
"""

from __future__ import annotations

import logging
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from verifier_agent import settings
from verifier_agent.card import Part
from verifier_agent.llm import judge_model
from verifier_agent.state import State
from verifier_agent.text import cut

log = logging.getLogger(__name__)

PROMPTS = Path(__file__).parent.parent / "prompts"


@lru_cache(maxsize=2)
def prompt(name: str) -> str:
    return (PROMPTS / name).read_text(encoding="utf-8")


class Judgement(BaseModel):
    """Your check: does the answer match the user's question?"""

    parts: list[Part] = Field(description="Each part of the question, and whether the answer responds to it")
    on_topic: bool = Field(description="False when the answer is about something other than what was asked")
    verdict: Literal["pass", "fail"] = Field(description="pass when every fact part is answered and it is on topic")
    summary: str = Field(description="One plain sentence: what matches, or exactly what does not")


def render(state: State) -> str:
    """The judge's input message (see prompts/judge_input.md)."""
    return prompt("judge_input.md").format(request=cut(state.get("request") or "", settings.MAX_REQUEST_CHARS),
                                           answer=cut(state["answer"]["text"], settings.MAX_ANSWER_CHARS))


def judge(state: State) -> dict:
    answer = state.get("answer")
    if not (answer and answer.get("text")):
        return {}  # nothing to judge: the rules report it
    try:
        model = judge_model()
    except Exception as exc:  # noqa: BLE001 - JudgeUnavailable: configured but unusable
        return {"judge_error": str(exc)}
    if model is None:
        return {"warnings": ["answer check skipped: VERIFIER_LLM_MODEL is not set (rule checks only)"]}

    system = prompt("judge_system.md").format(today=date.today().strftime("%d %B %Y"))
    llm = model.with_structured_output(Judgement, method="function_calling")
    try:
        out = llm.invoke([("system", system), ("human", render(state))])
        judgement = out if isinstance(out, Judgement) else Judgement.model_validate(out)
    except Exception as exc:  # noqa: BLE001 - timeout, rate limit, bad output: the check fails with the reason
        log.warning("judge failed: %s: %s", type(exc).__name__, exc)
        return {"judge_error": f"the checking model failed ({type(exc).__name__}: {str(exc)[:200]})"}
    return {"judgement": judgement.model_dump()}
