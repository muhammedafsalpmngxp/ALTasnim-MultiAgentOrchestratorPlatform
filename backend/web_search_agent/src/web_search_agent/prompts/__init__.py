"""Prompts live as Markdown files next to this module so they can be reviewed and edited without touching code.

Placeholders use `$name` (string.Template), so the prompts can contain braces and JSON freely.
"""

from functools import lru_cache
from importlib.resources import files
from string import Template


@lru_cache
def load(name: str) -> Template:
    return Template(files(__package__).joinpath(f"{name}.md").read_text(encoding="utf-8"))


def render(name: str, **values: object) -> str:
    return load(name).substitute(**values)
