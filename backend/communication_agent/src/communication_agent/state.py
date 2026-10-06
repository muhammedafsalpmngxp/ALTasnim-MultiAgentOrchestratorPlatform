from __future__ import annotations

from utils import AgentInput, AgentOutput


class State(AgentInput, AgentOutput, total=False):
    draft: dict  # EmailDraft.model_dump()
