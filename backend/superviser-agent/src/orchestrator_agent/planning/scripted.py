"""A supervisor without an LLM, for tests and offline demos: ``decide`` returns what the script returns.

    ScriptedSupervisor(lambda ctx: SupervisorDecision(action="answer", answer="Hi"))

``calls`` keeps every context it was given (mode, request, results, ...), so tests can check what the supervisor
was asked and how often.
"""

from __future__ import annotations

from collections.abc import Callable

from orchestrator_agent.planning.llm_supervisor import SupervisorContext
from utils import SupervisorDecision


class ScriptedSupervisor:
    def __init__(self, script: Callable[[SupervisorContext], SupervisorDecision]):
        self.script = script
        self.calls: list[SupervisorContext] = []

    def decide(self, ctx: SupervisorContext) -> SupervisorDecision:
        self.calls.append(ctx)
        return self.script(ctx)
