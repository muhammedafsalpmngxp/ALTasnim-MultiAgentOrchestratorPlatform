"""The verifier's card and its params / result models.

The platform runs the verifier itself (the supervisor's plan_guard adds a check step, found by role ``verifier``)
after every final answer. It checks ONE thing: does the answer match the user's question? It reads only the question
and the answer: no sources, no searching, no fact checking.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from utils import AgentCard


class VerifyParams(BaseModel):
    """``task.params`` of a check. Both optional: without them the task objective is the question and the input that
    has an ``answer`` is the answer."""

    request: str | None = Field(None, description="What the user asked, in their words")
    answer_step: str | None = Field(None, description="The input step whose output is the answer to check")


Fix = Literal["none", "rewrite_answer"]


class Part(BaseModel):
    part: str
    kind: Literal["fact", "action"] = Field("fact", description="action: something to be DONE (send, email, save), "
                                                                 "done by other steps after the check")
    answered: bool


class VerifyResult(BaseModel):
    """``result`` of the graph. ``status``/``summary`` for every agent; ``passed``/``issues``/``warnings`` as before."""

    status: Literal["ok", "failed"]
    passed: bool
    summary: str
    issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    rejected_steps: list[str] = Field(default_factory=list)
    fix: Fix = "none"
    parts: list[Part] = Field(default_factory=list)
    checked: dict = Field(default_factory=dict)  # answer_step, model


CARD = AgentCard(
    name="verifier",
    version="2.0.0",
    description="Checks that an answer matches the user's question: it responds to what was asked, covers every part "
                "of it, and is about the same thing (product, place, period). Reads only the question and the answer.",
    when_to_use="Run by the platform, not planned: after every final answer, before the user sees it.",
    when_not_to_use="Finding information, checking facts against sources, writing answers, sending messages.",
    examples=[
        "Check that the answer to 'details of India' talks about India and covers what was asked",
        "Check that the answer to 'compare the price in Oman and UAE' gives both prices",
    ],
    approval_mode="none",
    role="verifier",
    params_schema=VerifyParams.model_json_schema(),
    output_schema={
        "type": "object",
        "properties": {
            "status": {"type": "string", "description": "ok when passed, else failed"},
            "passed": {"type": "boolean"},
            "summary": {"type": "string", "description": "the verdict in one line"},
            "issues": {"type": "array", "items": {"type": "string"}, "description": "why it failed"},
            "warnings": {"type": "array", "items": {"type": "string"}},
            "missing": {"type": "array", "items": {"type": "string"},
                        "description": "parts of the question the answer does not respond to"},
            "rejected_steps": {"type": "array", "items": {"type": "string"},
                               "description": "the answer step, when it must be written again"},
            "fix": {"type": "string", "enum": ["none", "rewrite_answer"]},
        },
    },
    owner="team-quality",
)
