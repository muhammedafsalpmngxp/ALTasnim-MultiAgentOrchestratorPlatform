"""Chat models (langchain-openai), kept in one place so nodes never build clients themselves.

fast       WEB_SEARCH_OPENAI_FAST_MODEL       (gpt-4o-mini)   query planning

Tests replace `get_chat_model` with a fake model.
"""

from functools import lru_cache
from typing import Literal, TypeVar

import openai
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from web_search_agent.settings import get_settings

Tier = Literal["fast"]
T = TypeVar("T", bound=BaseModel)

# Worth retrying the node for (used in the nodes' RetryPolicy); anything else falls back gracefully.
TRANSIENT_ERRORS: tuple[type[Exception], ...] = (
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.RateLimitError,
    openai.InternalServerError,
)


def is_configured() -> bool:
    return get_settings().llm_configured


@lru_cache(maxsize=8)
def get_chat_model(tier: Tier, model: str) -> BaseChatModel:
    settings = get_settings()
    common = dict(
        model=model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url or None,
        timeout=settings.openai_timeout_seconds,
        max_retries=0,  # retries are the graph's job (RetryPolicy)
    )
    return ChatOpenAI(**common, temperature=0.1)


def structured(tier: Tier, model: str, schema: type[T]) -> Runnable:
    """Model that returns an instance of `schema` (OpenAI structured outputs, strict JSON schema)."""
    return get_chat_model(tier, model).with_structured_output(schema, method="json_schema", strict=True)
