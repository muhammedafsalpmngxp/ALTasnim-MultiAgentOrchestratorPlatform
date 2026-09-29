"""Agent registry: which agents exist, their cards, and how to call them.

transport=remote: cards are fetched from each deployment's ``GET /card`` custom
route and refreshed every ``CARD_TTL_SECONDS``. An agent that does not answer is
left out of planning until it is healthy again, so a team's deployment being
down never breaks the others.
"""

from __future__ import annotations

import importlib
import logging
import time
from dataclasses import dataclass, field

import httpx

from orchestrator_agent.clients import AgentClient, LocalAgentClient, RemoteAgentClient
from orchestrator_agent.settings import AgentConfig, AgentsConfig, load_agents_config
from utils import AgentCard

log = logging.getLogger(__name__)
CARD_TTL_SECONDS = 60
RETRY_SECONDS = 5


def _import(path: str):
    module, _, attr = path.partition(":")
    return getattr(importlib.import_module(module), attr)


@dataclass
class AgentEntry:
    name: str
    client: AgentClient
    card: AgentCard | None = None
    url: str | None = None
    fetched_at: float = field(default=float("-inf"))


class AgentRegistry:
    def __init__(self, entries: dict[str, AgentEntry]):
        self._entries = entries

    # ---- construction --------------------------------------------------- #
    @classmethod
    def from_config(cls, config: AgentsConfig | None = None) -> AgentRegistry:
        config = config or load_agents_config()
        entries: dict[str, AgentEntry] = {}
        for name, agent in config.agents.items():
            if not agent.enabled:
                continue
            entries[name] = cls._entry(name, agent, config.transport)
        return cls(entries)

    @staticmethod
    def _entry(name: str, agent: AgentConfig, transport: str) -> AgentEntry:
        if transport == "local":
            if not (agent.local_graph and agent.local_card):
                raise ValueError(f"agent {name!r}: local_graph and local_card are required for transport=local")
            return AgentEntry(name=name, client=LocalAgentClient(_import(agent.local_graph)),
                              card=_import(agent.local_card), fetched_at=float("inf"))
        if transport == "remote":
            if not (agent.url and agent.graph_id):
                raise ValueError(f"agent {name!r}: url and graph_id are required for transport=remote")
            return AgentEntry(name=name, client=RemoteAgentClient(agent.url, agent.graph_id), url=agent.url)
        raise ValueError(f"unknown transport {transport!r} (expected local | remote)")

    @classmethod
    def from_graphs(cls, graphs: dict[str, tuple[AgentCard, object]]) -> AgentRegistry:
        """For tests: {name: (card, compiled_graph)} with local transport."""
        return cls({name: AgentEntry(name=name, client=LocalAgentClient(graph), card=card, fetched_at=float("inf"))
                    for name, (card, graph) in graphs.items()})

    # ---- lookups -------------------------------------------------------- #
    def _refresh(self, entry: AgentEntry) -> None:
        if entry.url is None or time.monotonic() - entry.fetched_at < CARD_TTL_SECONDS:
            return
        try:
            resp = httpx.get(f"{entry.url.rstrip('/')}/card", timeout=5)
            resp.raise_for_status()
            entry.card = AgentCard.model_validate(resp.json())
            entry.fetched_at = time.monotonic()
        except Exception as exc:  # noqa: BLE001
            log.warning("agent %s unavailable at %s: %s", entry.name, entry.url, exc)
            entry.card = None
            entry.fetched_at = time.monotonic() - CARD_TTL_SECONDS + RETRY_SECONDS  # retry soon

    def cards(self) -> dict[str, AgentCard]:
        """Cards of healthy, enabled agents. The supervisor plans only with these."""
        out = {}
        for entry in self._entries.values():
            self._refresh(entry)
            if entry.card is not None:
                out[entry.name] = entry.card
        return out

    def client(self, name: str) -> AgentClient:
        if name not in self._entries:
            raise KeyError(f"agent {name!r} is not registered")
        return self._entries[name].client
