"""Agent registry: which agents exist, their cards, and how to call them.

transport=remote: every agent is a LangGraph deployment, called on its port + graph (config/agents.*.yaml,
AGENT_<NAME> in backend/.env). Its machine is found on the network (discovery.py) unless a fixed url is set.
Cards are fetched from each agent's ``GET /card`` (merged with the ``card`` fields of the config, then with the
planning text an admin customised, overrides.py) and refreshed every ``CARD_TTL_SECONDS``. An agent that does
not answer is left out of planning until it is healthy again, so a team's deployment being down never breaks the
others.
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
from orchestrator_agent.registry import discovery, overrides
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
    # what the admin page shows (set by every check)
    base: str | None = None  # the machine it was last found on
    error: str | None = None
    checked_at: float | None = None  # time.time()
    latency_ms: float | None = None  # GET /card
    paused: bool = False  # left out of planning by an admin (until the supervisor restarts)
    own: AgentCard | None = None  # the agent's own card (+ config card fields), before the admin's planning text
    overrides: dict = field(default_factory=dict)  # planning text an admin customised (overrides.py)

    def __post_init__(self) -> None:
        if self.own is None:
            self.own = self.card
        self.card = self.effective()

    def effective(self) -> AgentCard | None:
        """The card the supervisor plans with: its own, with the admin's planning text over it."""
        if self.own is None or not self.overrides:
            return self.own
        return AgentCard.model_validate({**self.own.model_dump(), **self.overrides})


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
        try:
            customised = overrides.load()
        except Exception as exc:  # noqa: BLE001 - a broken file must not stop the supervisor
            log.error("ignoring %s: %s", overrides.path(), exc)
            customised = {}
        for name, fields in customised.items():
            if name in entries:
                entries[name].overrides = fields
                entries[name].card = entries[name].effective()
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

    def _refresh(self, entry: AgentEntry, force: bool = False) -> None:
        if entry.locate is None or (not force and time.monotonic() - entry.fetched_at < CARD_TTL_SECONDS):
            return
        base = None
        try:
            base = entry.locate(entry.stale or force)
            if base is None:
                raise ConnectionError("no machine on the network serves it")
            started = time.perf_counter()
            resp = httpx.get(f"{base}/card", timeout=5)
            resp.raise_for_status()
            entry.latency_ms = round((time.perf_counter() - started) * 1000, 1)
            entry.own = AgentCard.model_validate({"name": entry.name, **resp.json(), **(entry.card_fields or {})})
            entry.card = entry.effective()
            entry.fetched_at, entry.stale, entry.error = time.monotonic(), False, None
        except Exception as exc:  # noqa: BLE001
            log.warning("agent %s unavailable%s: %s", entry.name, f" at {base}" if base else "", exc)
            entry.card, entry.stale, entry.error = None, True, f"{type(exc).__name__}: {exc}"
            entry.fetched_at = time.monotonic() - CARD_TTL_SECONDS + RETRY_SECONDS  # retry soon
        entry.base, entry.checked_at = base, time.time()

    def cards(self) -> dict[str, AgentCard]:
        """Cards of healthy, enabled, not paused agents. The supervisor plans only with these. The agents are
        checked in parallel (the first check may search the network)."""
        entries = list(self._entries.values())
        with ThreadPoolExecutor(max_workers=max(1, len(entries))) as pool:
            list(pool.map(self._refresh, entries))
        return {entry.name: entry.card for entry in entries if entry.card is not None and not entry.paused}

    # ---- admin ---------------------------------------------------------- #
    def _entry_named(self, name: str) -> AgentEntry:
        if name not in self._entries:
            raise KeyError(f"agent {name!r} is not a node of the supervisor (enable it in config/agents.*.yaml)")
        return self._entries[name]

    def recheck(self, name: str) -> None:
        """Search the network for the agent again and fetch its card now."""
        self._refresh(self._entry_named(name), force=True)

    def set_paused(self, name: str, paused: bool) -> None:
        """A paused agent stays a node but is left out of planning (e.g. to force web_search instead of rag)."""
        self._entry_named(name).paused = paused

    def customise(self, name: str, fields: dict) -> dict:
        """Set the agent's planning text (``overrides.FIELDS``; a field equal to its own card is not kept). The
        supervisor plans with it from the next question. Returns what is customised now."""
        e = self._entry_named(name)
        own = e.own.model_dump() if e.own else {}
        e.overrides = {k: v for k, v in fields.items() if k in overrides.FIELDS and v is not None and own.get(k) != v}
        if e.card is not None or e.locate is None:  # a down agent gets it with its next card
            e.card = e.effective()
        return dict(e.overrides)

    def status(self, name: str) -> dict:
        """What the admin page shows for one agent."""
        e = self._entry_named(name)
        if e.locate is None:
            state = "in_process"
        elif e.card is not None:
            state = "up"
        else:
            state = "down" if e.base else "not_found"
        return {
            "status": "paused" if e.paused else state,
            "reachable": e.locate is None or e.card is not None,
            "paused": e.paused,
            "url": e.base,
            "latency_ms": e.latency_ms,
            "checked_at": e.checked_at,
            "error": e.error,
            "card": e.card.model_dump() if e.card else None,
            "overrides": dict(e.overrides),
            # the agent's own planning text (what "reset" goes back to); None until its card was fetched once
            "planning_defaults": {f: getattr(e.own, f) for f in overrides.FIELDS} if e.own else None,
        }

    def client(self, name: str) -> AgentClient:
        if name not in self._entries:
            raise KeyError(f"agent {name!r} is not registered")
        return self._entries[name].client
