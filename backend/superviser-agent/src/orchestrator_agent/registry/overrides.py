"""Planning text an admin customised per agent: what the supervisor reads when it chooses agents.

Only the planning fields of a card (description, when to use / not to use, examples) can be customised; they are
merged over the agent's own card (its ``GET /card`` and the ``card`` fields of config/agents.*.yaml). Kept in a
YAML file so they survive restarts: env AGENT_OVERRIDES_FILE, default data/agent_overrides.yaml (docker-compose
mounts superviser-agent/data; not in git). Delete an agent's entry, or the file, to go back to the agents' own cards.
"""

from __future__ import annotations

import os
import threading
from typing import Annotated

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from orchestrator_agent.settings import _resolve

FIELDS = ("description", "when_to_use", "when_not_to_use", "examples")

_Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
_lock = threading.Lock()


class PlanningText(BaseModel):
    """The customisable fields. A field left out (or null) is the agent's own."""

    model_config = ConfigDict(extra="forbid")

    description: Annotated[_Text, StringConstraints(max_length=600)] | None = None
    when_to_use: Annotated[_Text, StringConstraints(max_length=1500)] | None = None
    when_not_to_use: Annotated[_Text, StringConstraints(max_length=1500)] | None = None
    examples: list[Annotated[_Text, StringConstraints(max_length=300)]] | None = Field(
        None, min_length=1, max_length=12)


def path():
    return _resolve(os.getenv("AGENT_OVERRIDES_FILE", "data/agent_overrides.yaml"))


def load() -> dict[str, dict]:
    """{agent: {field: value}}; a missing or empty file means nothing is customised."""
    file = path()
    if not file.is_file():
        return {}
    data = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
    return {name: PlanningText.model_validate(fields).model_dump(exclude_none=True) for name, fields in data.items()}


def save(name: str, fields: dict) -> None:
    """Set one agent's customisation (empty: remove it); every other agent's entry is kept."""
    with _lock:
        data = load()
        if fields:
            data[name] = fields
        else:
            data.pop(name, None)
        file = path()
        file.parent.mkdir(parents=True, exist_ok=True)
        tmp = file.with_suffix(".tmp")
        header = "# Written by the admin console (Admin -> Agents -> Planning). Merged over each agent's own card.\n"
        tmp.write_text(header + yaml.safe_dump(data, sort_keys=True, allow_unicode=True, width=120), encoding="utf-8")
        os.replace(tmp, file)  # never a half-written file
