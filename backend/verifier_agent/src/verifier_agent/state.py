from __future__ import annotations

import operator
from typing import Annotated, Any

from utils import AgentInput, AgentOutput


class State(AgentInput, AgentOutput, total=False):
    started: float  # perf_counter at collect, for the call log
    request: str  # what the user asked
    answer: dict[str, Any] | None  # {"step", "status", "text", "shape"} of the answer (None: no answer found)
    # rules and judge run in parallel and both write these
    issues: Annotated[list[str], operator.add]
    warnings: Annotated[list[str], operator.add]
    judgement: dict[str, Any] | None  # the judge's structured output (None: skipped or failed)
    judge_error: str | None
