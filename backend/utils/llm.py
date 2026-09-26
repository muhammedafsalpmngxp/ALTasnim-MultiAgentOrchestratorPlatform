"""Model factory. The only place that knows which LLM provider is used.

Configure with env vars (per deployment ``.env``)::

    LLM_MODEL_STRONG=azure_openai:gpt-4.1        # supervisor
    LLM_MODEL_STANDARD=azure_openai:gpt-4.1-mini # most agents
    LLM_MODEL_FAST=azure_openai:gpt-4.1-nano     # cheap sub-steps

The format is ``<provider>:<model>`` as accepted by ``init_chat_model``
(openai, azure_openai, anthropic, google_genai, bedrock, ollama, ...). Install
the matching integration package (e.g. ``langchain-openai``) in the deployment.

If no model is configured, ``get_model`` returns ``None``. Every node that uses
an LLM must then fall back to its rule-based path, so the whole platform runs
offline for development and tests.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from langchain_core.language_models import BaseChatModel

Tier = Literal["strong", "standard", "fast"]


def model_name(tier: Tier) -> str | None:
    return os.getenv(f"LLM_MODEL_{tier.upper()}") or os.getenv("LLM_MODEL") or None


def llm_enabled(tier: Tier = "standard") -> bool:
    return model_name(tier) is not None


@lru_cache(maxsize=8)
def get_model(tier: Tier = "standard") -> BaseChatModel | None:
    name = model_name(tier)
    if not name:
        return None
    from langchain.chat_models import init_chat_model

    return init_chat_model(name, temperature=0)
