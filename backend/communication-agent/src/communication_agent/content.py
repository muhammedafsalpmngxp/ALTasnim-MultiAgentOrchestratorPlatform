"""What the email may say: the content of the earlier steps (``task.inputs``) and their sources. Nothing else.

- a final answer (an output with ``answer``, e.g. the synthesizer's) is the content when there is one;
- otherwise every step's ``summary``, or the text of its ``findings`` / ``chunks`` (e.g. rag's passages);
- verifier verdicts (outputs with ``passed``) are checks, not content.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

MAX_CONTENT_CHARS = 8000
MAX_SOURCES = 8
URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")


@dataclass
class Content:
    text: str = ""
    sources: list[str] = field(default_factory=list)


def _items_text(out: dict) -> list[str]:
    parts = []
    for item in [*(out.get("findings") or []), *(out.get("chunks") or [])]:
        if isinstance(item, dict):
            body = str(item.get("content") or item.get("text") or item.get("snippet") or "").strip()
            label = item.get("title") or item.get("document_name") or ""
            if body:
                parts.append(f"{label}: {body}" if label else body)
    return parts


def _sources(out: dict) -> list[str]:
    found: list[str] = []
    for src in out.get("sources") or []:
        if isinstance(src, str):
            found.append(src)
        elif isinstance(src, dict) and (src.get("url") or src.get("title")):
            found.append(str(src.get("url") or src.get("title")))
    for item in [*(out.get("findings") or []), *(out.get("chunks") or [])]:
        if isinstance(item, dict):
            if item.get("url"):
                found.append(str(item["url"]))
            elif item.get("document_name"):
                found.append(f"Document: {item['document_name']}")
    return found


def collect(inputs: dict[str, Any]) -> Content:
    outputs = [out for out in inputs.values() if isinstance(out, dict) and "passed" not in out]
    answers = [out for out in outputs if str(out.get("answer") or "").strip()]
    parts: list[str] = []
    if answers:
        parts = [str(answers[-1]["answer"]).strip()]
    else:
        for out in outputs:
            if summary := str(out.get("summary") or "").strip():
                parts.append(summary)
            else:
                parts.extend(_items_text(out))
    sources = list(dict.fromkeys(s.strip() for out in outputs for s in _sources(out) if s and s.strip()))
    text = "\n\n".join(parts).strip()
    return Content(text=text[:MAX_CONTENT_CHARS], sources=sources[:MAX_SOURCES])
