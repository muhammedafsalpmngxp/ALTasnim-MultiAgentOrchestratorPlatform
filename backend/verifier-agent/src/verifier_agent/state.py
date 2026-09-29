from __future__ import annotations

import operator
from typing import Annotated

from utils import AgentInput, AgentOutput


def _merge(a: dict, b: dict) -> dict:
    return {**a, **b}


class State(AgentInput, AgentOutput, total=False):
    # The checks run in parallel and append here, so these need reducers.
    issues: Annotated[list[str], operator.add]
    warnings: Annotated[list[str], operator.add]
    judgements: Annotated[dict[str, dict], _merge]  # check_answer: step_id -> {verified, reason}
