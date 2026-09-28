"""
Which chat LLM is active: Qwen via Ollama ("local"), OpenAI, Groq or Gemini.

LLM_PROVIDER in backend/.env is the default. An admin can switch providers at runtime from the
UI (PUT /api/v1/models/active-provider). The choice is stored in RAGFlow's system_settings table,
so the API server and every task_executor replica pick it up on their next LLM call, with no
restart. Clearing the override returns to the .env default.

Every provider's own code path stays in place (e.g. Ollama's think=False / keep_alive handling in
rag/llm/chat_model.py) — this module only decides which one is used.
"""
import logging
from datetime import datetime

from api.core.config import settings

PROVIDERS = ("local", "openai", "groq", "gemini")
_SETTING_NAME = "lt.llm_provider"

logger = logging.getLogger(__name__)


def env_default_provider() -> str:
    return settings.LLM_PROVIDER.lower()


def get_override() -> str | None:
    """The admin-selected provider, or None when the .env default applies.

    Any DB problem also returns None, so chat keeps working on the .env default instead of failing."""
    try:
        from api.db.db_models import DB, SystemSettings
        with DB.connection_context():
            row = SystemSettings.get_or_none(SystemSettings.name == _SETTING_NAME)
    except Exception:
        logger.debug("Could not read the LLM provider override; using .env LLM_PROVIDER", exc_info=True)
        return None
    if row and row.value in PROVIDERS:
        return row.value
    return None


def get_active_provider() -> str:
    return get_override() or env_default_provider()


def is_configured(provider: str) -> bool:
    if provider == "local":
        return bool(settings.OLLAMA_BASE_URL and settings.OLLAMA_MODEL)
    return bool(settings.llm_api_key_for(provider))


def set_override(provider: str | None) -> None:
    """Store the admin's choice. None removes the override (back to the .env default)."""
    from peewee import IntegrityError

    from api.db.db_models import DB, SystemSettings
    from common.time_utils import current_timestamp, datetime_format

    now_ts, now_date = current_timestamp(), datetime_format(datetime.now())
    with DB.connection_context():
        if provider is None:
            SystemSettings.delete().where(SystemSettings.name == _SETTING_NAME).execute()
            return

        def _update() -> int:
            return (
                SystemSettings.update(value=provider, update_time=now_ts, update_date=now_date)
                .where(SystemSettings.name == _SETTING_NAME)
                .execute()
            )

        if _update():
            return
        try:
            SystemSettings.create(
                name=_SETTING_NAME,
                source="admin",
                data_type="string",
                value=provider,
                create_time=now_ts,
                create_date=now_date,
                update_time=now_ts,
                update_date=now_date,
            )
        except IntegrityError:
            _update()  # another request created the row between our update and insert
