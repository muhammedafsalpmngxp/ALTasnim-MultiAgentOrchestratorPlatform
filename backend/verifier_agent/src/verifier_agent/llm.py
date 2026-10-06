"""The judge's LLM (VERIFIER_LLM_MODEL). Built on first use and cached per model name."""

from __future__ import annotations

import re
from functools import lru_cache

from langchain_core.language_models import BaseChatModel

from verifier_agent import settings

# Reasoning models reject a temperature (OpenAI o-series and gpt-5.x).
_REASONING = re.compile(r"(^|:)(o\d|gpt-5)", re.IGNORECASE)


class JudgeUnavailable(RuntimeError):
    """The model is configured but cannot be created (missing package, bad name, ...)."""


@lru_cache(maxsize=4)
def _build(name: str) -> BaseChatModel:
    kwargs: dict = {"timeout": settings.LLM_TIMEOUT_SECONDS, "max_retries": settings.LLM_MAX_RETRIES}
    if not _REASONING.search(name):
        kwargs["temperature"] = 0
    if name.split(":", 1)[0] in ("openai", "azure_openai"):
        kwargs["use_responses_api"] = True  # reasoning models (gpt-5.x) take tools only on the Responses API
    from langchain.chat_models import init_chat_model

    try:
        return init_chat_model(name, **kwargs)
    except Exception as exc:  # noqa: BLE001 - one clear message in the verdict
        raise JudgeUnavailable(f"the checking model {name} cannot be used: {exc}") from exc


def judge_model() -> BaseChatModel | None:
    """The model of VERIFIER_LLM_MODEL, or None when it is not set (rule checks only)."""
    name = settings.model_name()
    return _build(name) if name else None
