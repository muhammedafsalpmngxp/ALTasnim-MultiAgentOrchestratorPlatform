"""The answer's text, whatever agent wrote it: its ``answer``, else its ``summary`` / ``text``. None-safe."""

from __future__ import annotations

from typing import Any


def text_of(out: Any) -> str:
    if not isinstance(out, dict):
        return str(out).strip() if out else ""
    return str(out.get("answer") or out.get("summary") or out.get("text") or "").strip()


def cut(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "\n[… cut: the rest was not shown]"
