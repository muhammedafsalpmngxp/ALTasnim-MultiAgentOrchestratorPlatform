"""LLM planner: the supervisor model returns a SupervisorDecision (structured output)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from utils import AgentCard, SupervisorDecision
from utils.llm import get_model

PROMPT = (Path(__file__).parent.parent / "prompts" / "supervisor.md").read_text(encoding="utf-8")


def render_agents(cards: dict[str, AgentCard]) -> str:
    blocks = []
    for card in cards.values():
        blocks.append(
            f"### {card.name}\n"
            f"- description: {card.description}\n"
            f"- when to use: {card.when_to_use}\n"
            f"- when NOT to use: {card.when_not_to_use}\n"
            f"- examples: {'; '.join(card.examples)}\n"
            f"- params JSON schema: {json.dumps(card.params_schema.get('properties', {}))}"
        )
    return "\n\n".join(blocks)


class LLMPlanner:
    def __init__(self, model=None):
        self._model = model or get_model("strong")
        self._structured = self._model.with_structured_output(SupervisorDecision)

    def decide(
        self,
        request: str,
        clarifications: list[str],
        cards: dict[str, AgentCard],
        done: dict[str, Any],
        feedback: list[str],
    ) -> SupervisorDecision:
        prompt = (
            PROMPT.replace("{{agents}}", render_agents(cards))
            .replace("{{request}}", request)
            .replace("{{clarifications}}", "\n".join(clarifications) or "(none)")
            .replace("{{done}}", json.dumps({k: v.get("summary", "") for k, v in done.items()}) or "{}")
            .replace("{{feedback}}", "\n".join(feedback) or "(none)")
        )
        return self._structured.invoke(prompt)
