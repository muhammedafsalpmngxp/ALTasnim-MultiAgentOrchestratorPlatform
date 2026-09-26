from __future__ import annotations

import operator
from typing import Annotated

from utils import AgentInput, AgentOutput


class State(AgentInput, AgentOutput, total=False):
    """Private state. Only ``task`` (in) and ``result`` (out) are visible to the orchestrator."""

    queries: list[str]
    max_sources: int
    # Written by parallel `search` branches, so it needs a reducer.
    findings: Annotated[list[dict], operator.add]
