"""The supervisor's own LLM (backend/.env). Each agent has its own model settings; this one only plans.

    SUPERVISOR_LLM_MODEL=openai:gpt-4o          # <provider>:<model>, as init_chat_model accepts (openai,
                                                # azure_openai, anthropic, ...); a bare name means openai
    SUPERVISOR_LLM_TEMPERATURE=0                # optional; leave empty for reasoning models (they reject it)
    SUPERVISOR_LLM_REASONING_EFFORT=low         # optional: low | medium | high (reasoning models only)
    SUPERVISOR_LLM_TIMEOUT_SECONDS=60           # optional
    SUPERVISOR_LLM_MAX_RETRIES=2                # optional
    SUPERVISOR_LLM_RESPONSES_API=true           # optional, openai / azure_openai: the Responses API (default),
                                                # needed by reasoning models (gpt-5.x) for tools; false = Chat
                                                # Completions

The provider's key comes from its usual variable (OPENAI_API_KEY for openai). The model is built on the first
question, not at import, so the server and the admin console start without it.
"""

from __future__ import annotations

import os
from functools import lru_cache

from langchain_core.language_models import BaseChatModel


class SupervisorLLMUnavailable(RuntimeError):
    """The supervisor cannot think: no model configured, or the model cannot be created."""


def _env(name: str) -> str:
    return os.getenv(name, "").strip().strip('"').strip("'")


def model_name() -> str | None:
    """``provider:model`` from SUPERVISOR_LLM_MODEL (``openai:`` added to a bare model name), or None."""
    name = _env("SUPERVISOR_LLM_MODEL")
    if not name:
        return None
    return name if ":" in name else f"openai:{name}"


def _number(name: str, kind: type, default=None):
    value = _env(name)
    if not value:
        return default
    try:
        return kind(value)
    except ValueError as exc:
        raise SupervisorLLMUnavailable(f"{name}={value!r} is not a valid {kind.__name__}") from exc


@lru_cache(maxsize=1)
def supervisor_model() -> BaseChatModel:
    name = model_name()
    if name is None:
        raise SupervisorLLMUnavailable(
            "The supervisor's LLM is not configured: set SUPERVISOR_LLM_MODEL (e.g. openai:gpt-4o) in backend/.env.")
    kwargs: dict = {
        "timeout": _number("SUPERVISOR_LLM_TIMEOUT_SECONDS", float, 60.0),
        "max_retries": _number("SUPERVISOR_LLM_MAX_RETRIES", int, 2),
    }
    temperature = _number("SUPERVISOR_LLM_TEMPERATURE", float)
    if temperature is not None:
        kwargs["temperature"] = temperature
    if effort := _env("SUPERVISOR_LLM_REASONING_EFFORT"):
        kwargs["reasoning_effort"] = effort
    if name.split(":", 1)[0] in ("openai", "azure_openai"):
        # Reasoning models (gpt-5.x) take tools with reasoning only on the Responses API.
        kwargs["use_responses_api"] = _env("SUPERVISOR_LLM_RESPONSES_API").lower() not in ("0", "false", "no")
    from langchain.chat_models import init_chat_model

    try:
        return init_chat_model(name, **kwargs)
    except Exception as exc:  # noqa: BLE001 - missing package or key: one clear message for the user
        raise SupervisorLLMUnavailable(f"The supervisor's LLM ({name}) cannot be used: {exc}") from exc
