import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

# Ensure backend/ is on the path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.core.config import settings

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    # force=True is REQUIRED here: sitecustomize.py (auto-imported at interpreter startup, before
    # this module) already attaches the rag_log_formatter highlight handler to the root logger, and
    # basicConfig() is a silent no-op if the root logger already has ANY handler. Without force, the
    # stdout StreamHandler that prints every formatted INFO log (startup banner, "Elasticsearch
    # healthy", LLMBundle.*, [RAG], [HISTORY], etc.) was never created — so all normal logs vanished
    # from `docker logs`. force=True re-establishes the stdout handler; the highlight handler is
    # then re-attached by the _install_rag_log_highlights() call below so both coexist.
    force=True,
)
logger = logging.getLogger("lt_assistant")

# Suppress noisy third-party debug/warning loggers
logging.getLogger("LiteLLM").setLevel(logging.WARNING)
logging.getLogger("litellm").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("peewee").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

# Purely additive: prints a colored highlight line whenever a RAG pipeline stage (router/
# retrieval) or a model call (embedding/rerank/LLM) logs, so it's easy to tell them apart and see
# token usage per call — does not change or remove any existing log line.
from api.core.rag_log_formatter import install as _install_rag_log_highlights  # noqa: E402
from api.core.rag_log_formatter import install_delayed as _install_rag_log_highlights_delayed  # noqa: E402

_install_rag_log_highlights()
# RAGFlow's own init (common.settings.init_settings(), called later in lifespan() below) resets
# the root logger's handlers, wiping the one just installed above — re-attach it once that's had
# time to finish.
_install_rag_log_highlights_delayed()


@asynccontextmanager
async def lifespan(app: FastAPI):
    rerank_display = settings.active_rerank_ragflow_id or "disabled"
    logger.info("=" * 60)
    logger.info(f"  {settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info(f"  ENV:       {settings.APP_ENV}")
    logger.info(f"  LLM:       {settings.LLM_PROVIDER} / {settings.active_llm_model}")
    logger.info(f"  Embedding: {settings.EMBEDDING_PROVIDER} / {settings.active_embedding_model}")
    logger.info(f"  Reranking: {rerank_display}")
    logger.info(f"  DB:        {settings.DB_TYPE}  | DOC ENGINE: {settings.DOC_ENGINE}")
    logger.info("=" * 60)

    # Ensure data directories exist
    Path(settings.STORAGE_PATH).mkdir(parents=True, exist_ok=True)
    Path(settings.DB_PATH).parent.mkdir(parents=True, exist_ok=True)

    # Initialize RAGFlow settings (DB, ES, Redis, LLM)
    try:
        from api.db.init_db import init_database
        init_database()
        logger.info("Database initialized")
    except Exception as e:
        logger.warning(f"DB init skipped: {e}")

    # Initialize RAGFlow common settings (FACTORY_LLM_INFOS, retriever, kg_retriever, etc.)
    try:
        from common.settings import init_settings
        init_settings()
        logger.info("RAGFlow common settings initialized (retriever + LLM factories loaded)")
    except Exception as e:
        logger.warning(f"RAGFlow common settings init skipped: {e}")

    # Initialize MinIO storage backend
    try:
        import common.settings as _cs
        from common.constants import Storage
        _cs.MINIO = _cs.decrypt_database_config(name="minio")
        _cs.STORAGE_IMPL = _cs.StorageFactory.create(Storage[_cs.STORAGE_IMPL_TYPE])
        logger.info(f"Storage backend initialized: {_cs.STORAGE_IMPL_TYPE}")
    except Exception as e:
        logger.warning(f"Storage init skipped: {e}")

    # The banner above shows the .env default; an admin may have switched the chat LLM at runtime.
    from api.core.llm_provider import get_override
    _llm_override = get_override()
    if _llm_override:
        logger.info(f"  LLM override (set by admin): {_llm_override} / {settings.llm_model_for(_llm_override)}")

    yield

    logger.info("Shutting down...")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="On-premise AI assistant for contract and engineering document research",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# ── Middleware ────────────────────────────────────────────────────────────────
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
from api.routes import (
    auth,
    chat,
    documents,
    models,
    projects,
    reports,
    search,
    system,
    users,
)

PREFIX = "/api/v1"

app.include_router(auth.router,      prefix=PREFIX, tags=["Auth"])
app.include_router(users.router,     prefix=PREFIX, tags=["Users"])
app.include_router(projects.router,  prefix=PREFIX, tags=["Projects"])
app.include_router(documents.router, prefix=PREFIX, tags=["Documents"])
app.include_router(search.router,    prefix=PREFIX, tags=["Search"])
app.include_router(chat.router,      prefix=PREFIX, tags=["Chat"])
app.include_router(reports.router,   prefix=PREFIX, tags=["Reports"])
app.include_router(models.router,    prefix=PREFIX, tags=["Models"])
app.include_router(system.router,    prefix=PREFIX, tags=["System"])


@app.get("/", include_in_schema=False)
async def root():
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "health": "/api/v1/system/health",
    }
