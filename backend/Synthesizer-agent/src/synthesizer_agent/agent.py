"""The whole synthesizer: take any input, put it in the prompt, return the LLM's answer.

prompts/system.md  how to work and how to format the answer (today's date is filled in)
prompts/user.md    the question, the numbered sources and the data
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# backend/Synthesizer-agent/src/synthesizer_agent/agent.py -> parents[3] == backend/. ENV_FILE points elsewhere, like
# utils/env.py; tests set it to an empty file (backend/conftest.py) so they never use your keys.
load_dotenv(Path(os.getenv("ENV_FILE", Path(__file__).resolve().parents[3] / ".env")), override=False)  # real env wins

_PROMPTS = Path(__file__).parent / "prompts"
_CITATION_RE = re.compile(r"\s*\[\d+(?:\s*[,-]\s*\d+)*\]")  # [1], [1, 2], [1-3]


def _prompt(name: str) -> str:
    """Read on every request, so edits to the prompt files apply without a restart."""
    return (_PROMPTS / name).read_text(encoding="utf-8")
MAX_INPUT_CHARS = 20000
log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _model():
    """The OpenAI LLM from SYNTHESIZER_OPENAI_* in backend/.env, or None if it is not configured.

    SYNTHESIZER_OPENAI_BASE_URL can point to OpenAI, Azure OpenAI, a proxy, or any OpenAI-compatible
    server such as Ollama (http://localhost:11434/v1).
    """
    model = os.getenv("SYNTHESIZER_OPENAI_MODEL")
    base_url = os.getenv("SYNTHESIZER_OPENAI_BASE_URL") or None  # empty = https://api.openai.com/v1
    api_key = os.getenv("SYNTHESIZER_OPENAI_API_KEY")
    if not model:
        return None
    if not api_key and (base_url is None or "api.openai.com" in base_url):
        log.warning("SYNTHESIZER_OPENAI_API_KEY is empty: answering without the LLM")
        return None
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=model,
        base_url=base_url,
        api_key=api_key or "not-needed",  # local servers (Ollama, LM Studio) ignore the key
        temperature=0.2,
        timeout=300,  # local models can be slow
    )


NO_QUESTION = ("(No question was given. Work out from the data what the user most likely wants to know, "
               "and answer that.)")
# Fields a sender may use for the question, checked in this order (also inside "task" / "params")
QUESTION_KEYS = ("question", "query", "q", "prompt", "user_question", "request", "message", "objective")


def _find_question(data: dict) -> tuple[str | None, dict]:
    """Take the question out of ``data``. Returns (question or None, the rest of the data)."""
    rest = dict(data)
    for key in QUESTION_KEYS:
        value = rest.get(key)
        if isinstance(value, str) and value.strip():
            del rest[key]
            return value.strip(), rest
    for parent in ("task", "params", "input", "data"):  # one level deeper, e.g. {"task": {"objective": ...}}
        if isinstance(rest.get(parent), dict):
            question, inner = _find_question(rest[parent])
            if question:
                rest[parent] = inner
                return question, rest
    return None, rest


def split_request(body: Any) -> tuple[str | None, dict[str, Any]]:
    """Any request body (JSON object, list, text) -> (question or None, inputs for the prompt)."""
    if isinstance(body, dict):
        question, rest = _find_question(body)
        if set(rest) == {"inputs"} and isinstance(rest["inputs"], dict):  # our own {"question", "inputs"} shape
            return question, rest["inputs"]
        return question, rest
    if isinstance(body, str):
        return None, {"text": body} if body.strip() else {}
    return None, {"data": body} if body not in (None, [], "") else {}


def _urls(value: Any, depth: int = 0) -> list[str]:
    """Source URLs anywhere in the data: "sources": [...] lists and "url" fields."""
    if depth > 5:
        return []
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "sources" and isinstance(item, list):
                found += [u for u in item if isinstance(u, str) and u.startswith(("http://", "https://"))]
            elif key == "url" and isinstance(item, str) and item.startswith(("http://", "https://")):
                found.append(item)
            else:
                found += _urls(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            found += _urls(item, depth + 1)
    return found


def build_messages(question: str | None, inputs: dict[str, Any]) -> list[tuple[str, str]]:
    """System + user message for the LLM."""
    data = json.dumps(inputs, indent=2, ensure_ascii=False, default=str)[:MAX_INPUT_CHARS]
    user = _prompt("user.md").format(question=question or NO_QUESTION, data=data)
    return [("system", _prompt("system.md").format(today=date.today().strftime("%d %B %Y"))), ("human", user)]


def build_prompt(question: str | None, inputs: dict[str, Any]) -> str:
    """The same messages as one text, for the UI."""
    return "\n\n".join(f"===== {role.upper()} =====\n{text}" for role, text in build_messages(question, inputs))


def llm_info() -> dict | None:
    """Which LLM answers (shown in the UI), or None when no LLM is configured."""
    model = _model()
    if model is None:
        return None
    return {"model": getattr(model, "model_name", type(model).__name__),
            "base_url": getattr(model, "openai_api_base", None) or "https://api.openai.com/v1"}


def answer(question: str | None, inputs: dict[str, Any]) -> dict:
    """``inputs`` holds the outputs of the earlier agents (e.g. web search chunks), in any shape."""
    if not inputs:
        return {"status": "failed", "summary": "Nothing to answer from: the request had no data"}

    model = _model()
    if model is None:  # no LLM configured: return the inputs' summaries
        text = "\n\n".join(str(out.get("summary", out)) if isinstance(out, dict) else str(out)
                           for out in inputs.values())
    else:
        reply = model.invoke(build_messages(question, inputs))
        text = re.sub(r"<think>.*?</think>", "", reply.text, flags=re.S)  # reasoning models
        text = _CITATION_RE.sub("", text).strip()  # shown without [1]-style references

    return {"status": "ok", "summary": text, "answer": text, "sources": list(dict.fromkeys(_urls(inputs)))}
