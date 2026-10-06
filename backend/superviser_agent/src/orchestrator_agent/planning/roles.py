"""Agents by role (AgentCard.role). The supervisor's code never names an agent: it asks for a role."""

from __future__ import annotations

from utils import AgentCard


def agents_with_role(cards: dict[str, AgentCard], role: str) -> set[str]:
    return {name for name, card in cards.items() if card.role == role}
