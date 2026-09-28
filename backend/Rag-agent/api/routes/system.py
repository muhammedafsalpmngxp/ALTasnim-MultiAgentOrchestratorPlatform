"""
System health, diagnostics, and admin endpoints.
"""
import time

from fastapi import APIRouter, HTTPException

from api.core.config import settings
from api.core.deps import AdminUser, AuthUser
from api.core.llm_provider import get_active_provider, is_configured

router = APIRouter()

_START_TIME = time.time()


@router.get("/health")
async def health_check():
    """Public health check — no auth required."""
    return {"status": "ok", "service": "L&T Files Assistant"}


@router.get("/system/status")
async def system_status(user: AuthUser):
    """Full system status for authenticated users."""
    status = {
        "app": {"status": "ok", "uptime_seconds": int(time.time() - _START_TIME)},
        "database": _check_db(),
        "elasticsearch": _check_es(),
        "redis": _check_redis(),
        "llm": _check_llm(),
    }
    overall = all(v.get("status") == "ok" for v in status.values() if isinstance(v, dict))
    return {"overall": "ok" if overall else "degraded", **status}


@router.get("/system/info")
async def system_info(user: AdminUser):
    """Detailed system info for admins."""
    embd = settings.active_embedding_ragflow_id or "not configured"
    rerank = settings.active_rerank_ragflow_id or "not configured"
    return {
        "app_name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.APP_ENV,
        "db_type": settings.DB_TYPE,
        "llm_provider": get_active_provider(),
        "llm_provider_default": settings.LLM_PROVIDER,
        "llm_model": settings.llm_model_for(get_active_provider()),
        "doc_engine": settings.DOC_ENGINE,
        "embedding_provider": settings.EMBEDDING_PROVIDER,
        "embedding_model": embd,
        "rerank_provider": settings.RERANK_PROVIDER or "disabled",
        "rerank_model": rerank,
        "max_upload_mb": settings.MAX_UPLOAD_SIZE_MB,
    }


@router.get("/system/parsers")
async def list_parsers(user: AuthUser):
    """List all available document parsers."""
    return {
        "parsers": [
            {"id": "naive",   "name": "General",         "description": "General-purpose chunker for any document"},
            {"id": "paper",   "name": "Academic Paper",  "description": "Optimized for research papers with sections"},
            {"id": "book",    "name": "Book",             "description": "Long-form books with chapters"},
            {"id": "laws",    "name": "Laws / Regulations", "description": "Legal documents and regulations"},
            {"id": "manual",  "name": "Manual",           "description": "Technical manuals and documentation"},
            {"id": "qa",      "name": "Q&A",              "description": "Q&A format documents"},
            {"id": "table",   "name": "Table",            "description": "Tabular data in Excel/CSV"},
            {"id": "resume",  "name": "Resume",           "description": "Resumes and CVs"},
            {"id": "picture", "name": "Picture",          "description": "Image-heavy documents"},
            {"id": "one",     "name": "One (No Chunk)",   "description": "Keep document as single chunk"},
            {"id": "audio",   "name": "Audio",            "description": "Audio files via transcription"},
            {"id": "email",   "name": "Email",            "description": "Email format"},
            {"id": "tag",     "name": "Tag",              "description": "Structured tag documents"},
            {"id": "knowledge_graph", "name": "Knowledge Graph", "description": "GraphRAG entity extraction"},
        ]
    }


@router.post("/system/reindex/{project_id}")
async def reindex_project(project_id: str, user: AdminUser):
    """Re-push all documents in a project to the task queue."""
    try:
        from api.db.services.knowledgebase_service import KnowledgebaseService
        from api.db.services.document_service import DocumentService
        from api.db.services.task_service import TaskService
        from api.db.db_models import Task

        _, kb = KnowledgebaseService.get_by_id(project_id)
        if not kb or str(kb.tenant_id) != user.tenant_id:
            raise HTTPException(status_code=404, detail="Project not found")

        # Auto-update KB embedding model to current active model
        new_embd_id = settings.active_embedding_ragflow_id
        if kb.embd_id != new_embd_id:
            KnowledgebaseService.update_by_id(project_id, {"embd_id": new_embd_id})

        docs = DocumentService.query(kb_id=project_id, status="1")
        kb_table_num_map = {}
        count = 0
        import logging
        from rag.nlp import search as rag_search
        from common import settings as _cs
        index_name = rag_search.index_name(user.tenant_id)
        for d in docs:
            doc_id = str(d.id)
            doc_dict = d.__data__.copy()
            doc_dict["id"] = doc_id
            doc_dict["kb_id"] = str(d.kb_id)
            # Clear old ES chunks to avoid duplicates
            try:
                _cs.docStoreConn.delete({"doc_id": doc_id}, index_name, str(d.kb_id))
            except Exception as ex:
                logging.warning(f"Failed to clear ES chunks for doc {doc_id}: {ex}")
            # Reset document state
            DocumentService.update_by_id(doc_id, {"run": "0", "progress": 0.0, "progress_msg": "", "chunk_num": 0, "token_num": 0})
            # Delete old tasks so queue_tasks creates fresh ones
            TaskService.filter_delete([Task.doc_id == doc_id])
            try:
                DocumentService.run(user.tenant_id, doc_dict, kb_table_num_map)
                count += 1
            except Exception as ex:
                logging.warning(f"Failed to queue doc {doc_id}: {ex}")

        return {"message": f"Queued {count} documents for re-indexing with embedding model '{new_embd_id}'"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _check_db() -> dict:
    try:
        from api.db import db_models
        db_models.DB.execute_sql("SELECT 1")
        return {"status": "ok", "type": settings.DB_TYPE}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _check_es() -> dict:
    try:
        import requests
        resp = requests.get(settings.ES_HOST, timeout=3)
        info = resp.json()
        return {"status": "ok", "version": info["version"]["number"]}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _check_redis() -> dict:
    try:
        import redis
        password = settings.REDIS_PASSWORD
        auth = f":{password}@" if password else ""
        url = f"redis://{auth}{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}"
        r = redis.from_url(url)
        r.ping()
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _check_llm() -> dict:
    provider = get_active_provider()
    configured = is_configured(provider)  # Ollama has no API key; cloud providers need one
    return {
        "status": "ok" if configured else "warning",
        "provider": provider,
        "model": settings.llm_model_for(provider),
        "configured": configured,
    }
