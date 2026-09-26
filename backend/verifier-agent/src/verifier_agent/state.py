from __future__ import annotations

import operator
from typing import Annotated

from utils import AgentInput, AgentOutput


class State(AgentInput, AgentOutput, total=False):
    # Both checks run in parallel and append here, so these need reducers.
    issues: Annotated[list[str], operator.add]
    warnings: Annotated[list[str], operator.add]
