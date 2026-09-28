"""
LLM, embedding, and reranking model configuration.
All providers resolved from .env via pydantic BaseSettings; the active chat provider can also be
switched at runtime by an admin (see api/core/llm_provider.py).
"""
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.core.config import settings
from api.core.deps import AdminUser, AuthUser
from api.core.llm_provider import (
    PROVIDERS,
    env_default_provider,
    get_active_provider,
    get_override,
    is_configured,
    set_override,
)

router = APIRouter()

_PROVIDER_NAMES = {
    "local": "Ollama (Local)",
    "openai": "OpenAI",
    "groq": "Groq (free tier)",
    "gemini": "Google Gemini",
}
_PROVIDER_KEY_VARS = {"openai": "OPENAI_API_KEY", "groq": "GROQ_API_KEY", "gemini": "GEMINI_API_KEY"}


class SetProviderRequest(BaseModel):
    provider: Optional[str] = None   # None = clear the override, back to LLM_PROVIDER in .env


def _providers_payload() -> dict:
    override = get_override()
    active = override or env_default_provider()
    providers = [
        {
            "id": pid,
            "name": _PROVIDER_NAMES[pid],
            "active": active == pid,
            "configured": is_configured(pid),
            "model": settings.llm_model_for(pid),
        }
        for pid in ("openai", "groq", "gemini", "local")
    ]
    return {
        "active_provider": active,
        "default_provider": env_default_provider(),   # LLM_PROVIDER in backend/.env
        "overridden": override is not None,            # True when an admin switched it at runtime
        "providers": providers,
    }


@router.get("/models/providers")
async def list_providers(user: AuthUser):
    """All supported LLM providers with active/configured status."""
    return _providers_payload()


@router.put("/models/active-provider")
async def set_active_provider(req: SetProviderRequest, user: AdminUser):
    """Switch the chat LLM for the whole app (admin only). Takes effect on the next LLM call in
    the API and every task_executor, with no restart. provider=null returns to the .env default."""
    provider = req.provider.strip().lower() if req.provider else None
    if provider is not None:
        if provider not in PROVIDERS:
            raise HTTPException(status_code=400, detail=f"Unknown provider '{provider}'. Use one of: {', '.join(PROVIDERS)}")
        if not is_configured(provider):
            hint = f"set {_PROVIDER_KEY_VARS[provider]}" if provider in _PROVIDER_KEY_VARS else "set OLLAMA_BASE_URL and OLLAMA_MODEL"
            raise HTTPException(
                status_code=400,
                detail=f"{_PROVIDER_NAMES[provider]} is not configured — {hint} in backend/.env and restart the backend",
            )
    try:
        set_override(provider)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not save the provider setting: {e}")
    import logging
    logging.getLogger(__name__).info(
        "[LLM] admin %s switched chat provider to %s", user.username, provider or f"{env_default_provider()} (.env default)"
    )
    return _providers_payload()


@router.get("/models/active")
async def get_active_model(user: AuthUser):
    """Active LLM + embedding + reranker. The LLM is the admin's runtime choice, else .env."""
    provider = get_active_provider()
    base_url_map = {
        "local":  settings.OLLAMA_BASE_URL,
        "openai": settings.OPENAI_BASE_URL,
        "groq":   "https://api.groq.com/openai/v1",
        "gemini": "https://generativelanguage.googleapis.com/v1beta",
    }
    return {
        # ── LLM ──────────────────────────────────────────
        "llm": {
            "provider": provider,
            "model":    settings.llm_model_for(provider),
            "base_url": base_url_map.get(provider, ""),
            "source":   "admin" if get_override() else ".env",
        },
        # ── Embedding ────────────────────────────────────
        "embedding": {
            "provider":   settings.EMBEDDING_PROVIDER,
            "model":      settings.active_embedding_model,
            "factory":    settings.active_embedding_factory,
            "ragflow_id": settings.active_embedding_ragflow_id,
        },
        # ── Reranking ────────────────────────────────────
        "reranking": {
            "provider":   settings.RERANK_PROVIDER or "disabled",
            "model":      settings.active_rerank_model or "disabled",
            "factory":    settings.active_rerank_factory or "disabled",
            "ragflow_id": settings.active_rerank_ragflow_id or "disabled",
            "enabled":    bool(settings.active_rerank_ragflow_id),
        },
    }


@router.get("/models/embedding")
async def get_embedding_config(user: AuthUser):
    """All embedding provider options and which is active."""
    return {
        "active_provider": settings.EMBEDDING_PROVIDER,
        "active_model":    settings.active_embedding_model,
        "active_factory":  settings.active_embedding_factory,
        "ragflow_id":      settings.active_embedding_ragflow_id,
        "options": {
            "openai": {
                "model":       settings.OPENAI_EMBEDDING_MODEL,
                "factory":     "OpenAI",
                "requires_key": True,
                "cost":         "paid",
            },
            "bge": {
                "model":       settings.BGE_EMBEDDING_MODEL,
                "factory":     "BAAI",
                "requires_key": False,
                "cost":         "free",
            },
            "local": {
                "model":       settings.LOCAL_EMBEDDING_MODEL,
                "factory":     "Ollama",
                "requires_key": False,
                "cost":         "free (runs on your machine)",
            },
        },
    }


@router.get("/models/rerank")
async def get_rerank_config(user: AuthUser):
    """Reranking provider options and which is active."""
    return {
        "active_provider": settings.RERANK_PROVIDER or "disabled",
        "active_model":    settings.active_rerank_model or "disabled",
        "active_factory":  settings.active_rerank_factory or "disabled",
        "ragflow_id":      settings.active_rerank_ragflow_id or "disabled",
        "enabled":         bool(settings.active_rerank_ragflow_id),
        "options": {
            "bge": {
                "model":       settings.BGE_RERANK_MODEL,
                "factory":     "BAAI",
                "requires_key": False,
                "cost":         "free",
                "note":         "Set RERANK_PROVIDER=bge in .env to enable",
            },
            "local": {
                "model":       settings.LOCAL_RERANK_MODEL,
                "factory":     "Ollama",
                "requires_key": False,
                "cost":         "free (runs on your machine)",
                "note":         "Set RERANK_PROVIDER=local in .env to enable",
            },
        },
    }


@router.post("/models/test")
async def test_llm_connection(user: AdminUser):
    """Test the active LLM provider with a live call (admin only)."""
    try:
        from litellm import completion
        provider = get_active_provider()
        model_map = {
            "local":  f"ollama/{settings.OLLAMA_MODEL}",
            "openai": settings.OPENAI_MODEL,
            "groq":   f"groq/{settings.GROQ_MODEL}",
            "gemini": f"gemini/{settings.GEMINI_MODEL}",
        }
        model_id = model_map.get(provider, "")
        kwargs = {
            "model": model_id,
            "messages": [{"role": "user", "content": "Reply with 'ok' only."}],
            "max_tokens": 5,
        }
        if provider == "local":
            kwargs["api_base"] = settings.OLLAMA_BASE_URL
        elif provider == "openai":
            kwargs["api_key"] = settings.OPENAI_API_KEY
            kwargs["api_base"] = settings.OPENAI_BASE_URL
        elif provider == "groq":
            kwargs["api_key"] = settings.GROQ_API_KEY
        elif provider == "gemini":
            kwargs["api_key"] = settings.GEMINI_API_KEY

        response = completion(**kwargs)
        return {
            "status": "ok",
            "provider": provider,
            "model": model_id,
            "reply": response.choices[0].message.content,
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"LLM connection failed: {str(e)}")
