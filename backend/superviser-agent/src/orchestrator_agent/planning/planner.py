"""Planner interface + factory. LLM planner when LLM_MODEL_STRONG is set, else rules."""

from __future__ import annotations

from typing import Any, Protocol

from utils import AgentCard, SupervisorDecision
from utils.llm import llm_enabled


class Planner(Protocol):
    def decide(
        self,
        request: str,
        clarifications: list[str],
        cards: dict[str, AgentCard],
        done: dict[str, Any],
        feedback: list[str],
    ) -> SupervisorDecision: ...


def default_planner() -> Planner:
    if llm_enabled("strong"):
        from orchestrator_agent.planning.llm_planner import LLMPlanner

        return LLMPlanner()
    from orchestrator_agent.planning.rule_planner import RulePlanner

    return RulePlanner()
