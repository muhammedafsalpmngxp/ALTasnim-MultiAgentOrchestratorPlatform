"""Shared model tiers, for agents that use them (today: the verifier's fallback when VERIFIER_LLM_MODEL is unset).

Configure with env vars (backend/.env)::

    LLM_MODEL_STANDARD=openai:gpt-4o-mini        # checks, drafting
    LLM_MODEL_FAST=openai:gpt-4o-mini            # cheap sub-steps

The format is ``<provider>:<model>`` as accepted by ``init_chat_model``
(openai, azure_openai, anthropic, google_genai, bedrock, ollama, ...). Install
the matching integration package (e.g. ``langchain-openai``) in the deployment.

Agents with their own model setting do not use these tiers: the supervisor (SUPERVISOR_LLM_MODEL), the
communication agent (COMMUNICATION_LLM_MODEL), the synthesizer (SYNTHESIZER_OPENAI_MODEL) and web search
(WEB_SEARCH_OPENAI_*). If no model is configured, ``get_model`` returns ``None`` and the caller skips its LLM step.
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
