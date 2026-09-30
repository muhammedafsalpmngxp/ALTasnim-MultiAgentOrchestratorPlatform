"""Agent registry: which agents exist, their cards, and how to call them.

transport=remote: every agent is a LangGraph deployment, called on its port + graph (config/agents.*.yaml,
AGENT_<NAME> in backend/.env). Its machine is found on the network (discovery.py) unless a fixed url is set.
Cards are fetched from each agent's ``GET /card`` (merged with the ``card`` fields of the config) and refreshed
every ``CARD_TTL_SECONDS``. An agent that does not answer is left out of planning until it is healthy again,
so a team's deployment being down never breaks the others.
"""

from __future__ import annotations

import importlib
import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import partial

import httpx

from orchestrator_agent.clients import AgentClient, LocalAgentClient, RemoteAgentClient
from orchestrator_agent.registry import discovery
from orchestrator_agent.settings import AgentConfig, AgentsConfig, load_agents_config
from utils import AgentCard

log = logging.getLogger(__name__)
CARD_TTL_SECONDS = 60
RETRY_SECONDS = 5


def _locate(port: int, graph_id: str, subnet: str, refresh: bool) -> str | None:
    return discovery.locate(port, graph_id, subnet=subnet, refresh=refresh)


def _fixed(base: str, refresh: bool) -> str:
    return base


def _import(path: str):
    module, _, attr = path.partition(":")
    return getattr(importlib.import_module(module), attr)


@dataclass
class AgentEntry:
    name: str
    client: AgentClient
    card: AgentCard | None = None
    # (refresh) -> base URL of the agent's machine or None; None = in-process (local transport)
    locate: Callable[[bool], str | None] | None = None
    card_fields: dict | None = None  # merged over the agent's own card
    fetched_at: float = field(default=float("-inf"))
    stale: bool = False  # the last card fetch failed: search the network again


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
            entries[name] = cls._entry(name, agent, config)
        return cls(entries)

    @staticmethod
    def _entry(name: str, agent: AgentConfig, config: AgentsConfig) -> AgentEntry:
        if config.transport not in ("local", "remote"):
            raise ValueError(f"unknown transport {config.transport!r} (expected local | remote)")
        if config.transport == "local" and agent.local_graph and agent.local_card:  # in-process (dev, tests)
            return AgentEntry(name=name, client=LocalAgentClient(_import(agent.local_graph)),
                              card=_import(agent.local_card), fetched_at=float("inf"))
        if not agent.graph_id or not (agent.port or agent.url):
            raise ValueError(f"agent {name!r}: set its graph_id and its port (or a url)")
        if agent.url:
            locate = partial(_fixed, agent.url.rstrip("/"))
        else:
            locate = partial(_locate, agent.port, agent.graph_id, config.subnet)
        return AgentEntry(name=name, client=RemoteAgentClient(locate, agent.graph_id), locate=locate,
                          card_fields=agent.card)

    @classmethod
    def from_graphs(cls, graphs: dict[str, tuple[AgentCard, object]]) -> AgentRegistry:
        """For tests: {name: (card, compiled_graph)} with local transport."""
        return cls({name: AgentEntry(name=name, client=LocalAgentClient(graph), card=card, fetched_at=float("inf"))
                    for name, (card, graph) in graphs.items()})

    # ---- lookups -------------------------------------------------------- #
    def names(self) -> list[str]:
        """Every registered (enabled) agent, healthy or not: each is a node of the supervisor graph."""
        return list(self._entries)

    def _refresh(self, entry: AgentEntry) -> None:
        if entry.locate is None or time.monotonic() - entry.fetched_at < CARD_TTL_SECONDS:
            return
        base = None
        try:
            base = entry.locate(entry.stale)
            if base is None:
                raise ConnectionError("no machine on the network serves it")
            resp = httpx.get(f"{base}/card", timeout=5)
            resp.raise_for_status()
            entry.card = AgentCard.model_validate({"name": entry.name, **resp.json(), **(entry.card_fields or {})})
            entry.fetched_at, entry.stale = time.monotonic(), False
        except Exception as exc:  # noqa: BLE001
            log.warning("agent %s unavailable%s: %s", entry.name, f" at {base}" if base else "", exc)
            entry.card, entry.stale = None, True
            entry.fetched_at = time.monotonic() - CARD_TTL_SECONDS + RETRY_SECONDS  # retry soon

    def cards(self) -> dict[str, AgentCard]:
        """Cards of healthy, enabled agents. The supervisor plans only with these. The agents are checked in
        parallel (the first check may search the network)."""
        entries = list(self._entries.values())
        with ThreadPoolExecutor(max_workers=max(1, len(entries))) as pool:
            list(pool.map(self._refresh, entries))
        return {entry.name: entry.card for entry in entries if entry.card is not None}

    def client(self, name: str) -> AgentClient:
        if name not in self._entries:
            raise KeyError(f"agent {name!r} is not registered")
        return self._entries[name].client
