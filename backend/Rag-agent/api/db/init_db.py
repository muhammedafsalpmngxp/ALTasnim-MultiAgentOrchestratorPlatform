"""
Database initialization — supports SQLite (dev), MySQL, PostgreSQL.
Uses Peewee ORM (same as RAGFlow).
"""
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def get_database():
    """Return a Peewee database instance based on LT_DB_TYPE env var.
    Uses LT_DB_TYPE (not DB_TYPE) to avoid collision with RAGFlow's internal DB_TYPE."""
    db_type = os.getenv("LT_DB_TYPE", os.getenv("DB_TYPE", "sqlite")).lower()

    if db_type == "sqlite":
        from peewee import SqliteDatabase
        db_path = os.getenv("DB_PATH", "./data/lt_assistant.db")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"Using SQLite: {db_path}")
        return SqliteDatabase(
            db_path,
            pragmas={"journal_mode": "wal", "foreign_keys": 1, "cache_size": -64 * 1000},
        )

    if db_type == "mysql":
        from playhouse.pool import PooledMySQLDatabase
        return PooledMySQLDatabase(
            os.getenv("DB_NAME", "lt_assistant"),
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", 3306)),
            user=os.getenv("DB_USER", "root"),
            password=os.getenv("DB_PASSWORD", ""),
            charset="utf8mb4",
            max_connections=20,
            stale_timeout=300,
        )

    if db_type == "postgresql":
        from playhouse.pool import PooledPostgresqlDatabase
        return PooledPostgresqlDatabase(
            os.getenv("DB_NAME", "lt_assistant"),
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", 5432)),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD", ""),
            max_connections=20,
            stale_timeout=300,
        )

    raise ValueError(f"Unsupported DB_TYPE: {db_type}. Use sqlite | mysql | postgresql")


def init_database():
    """Initialize DB connection and create tables.

    All Peewee models bind to db_models.DB at import time — RAGFlow's concrete pooled
    connection (MySQL/PostgreSQL/OceanBase) built from service_conf.yaml. We therefore create
    the tables on THAT connection using RAGFlow's own model enumerator (init_database_tables),
    which discovers every DataBaseModel subclass and creates any missing table.

    The previous implementation called db_models.DB.initialize(get_database()) followed by
    create_tables(db_models.ALL_MODELS) — but this db_models.py exposes neither a DatabaseProxy
    (so .initialize() raised AttributeError) nor an ALL_MODELS list. Those were leftovers from
    an older custom db_models module; the crash meant NO tables were ever created, so every
    DB-backed endpoint (e.g. /projects) returned 500.
    """
    from api.db import db_models

    db_models.init_database_tables()

    logger.info("Database tables ready")

    # Ensure the default tenant exists (required for document→knowledgebase→tenant JOIN)
    _ensure_default_tenant(db_models)

    # Register embedding (and rerank) provider in tenant model registry
    # so the refactored task executor can resolve the model at parse time
    _ensure_model_providers(db_models)

    # Migrate any existing KBs that still have the old embd_id format (model___factory)
    _migrate_embd_id_format()


def _ensure_default_tenant(db_models):
    """Create the 'default' tenant row if it doesn't exist."""
    try:
        from api.db.db_models import Tenant
        exists = Tenant.select().where(Tenant.id == "default").count()
        if not exists:
            Tenant.insert({
                "id": "default",
                "name": "L&T Files Assistant",
                "llm_id": "",
                "embd_id": "",
                "asr_id": "",
                "img2txt_id": "",
                "rerank_id": "",
                "parser_ids": "naive:General,qa:Q&A,resume:Resume,manual:Manual,table:Table,paper:Paper,book:Book,laws:Laws,presentation:Presentation,picture:Picture,one:One,audio:Audio,email:Email,tag:Tag",
                "credit": 512,
                "status": "1",
            }).execute()
            logger.info("Default tenant created")
    except Exception as e:
        logger.warning(f"Could not create default tenant: {e}")


def _ensure_model_providers(db_models):
    """Register embedding and rerank models in tenant model registry.

    The refactored task executor resolves models via:
      TenantModelProvider → TenantModelInstance → TenantModel
    using embd_id format:  model_name@instance_name@provider_name
    """
    import uuid
    from api.core.config import settings

    try:
        from api.db.db_models import TenantModelProvider, TenantModelInstance, TenantModel

        providers_to_register = []

        # Embedding provider
        embd_factory = settings.active_embedding_factory
        embd_model = settings.active_embedding_model
        embd_api_key = settings.OPENAI_API_KEY if embd_factory == "OpenAI" else ""
        providers_to_register.append({
            "provider_name": embd_factory,
            "model_name": embd_model,
            "model_type": "embedding",
            "api_key": embd_api_key,
        })

        # Rerank provider (if enabled)
        rerank_factory = settings.active_rerank_factory
        rerank_model = settings.active_rerank_model
        if rerank_factory and rerank_model:
            providers_to_register.append({
                "provider_name": rerank_factory,
                "model_name": rerank_model,
                "model_type": "rerank",
                "api_key": "",
            })

        for entry in providers_to_register:
            pname = entry["provider_name"]
            # Find or create provider row
            try:
                prov = TenantModelProvider.get(
                    TenantModelProvider.tenant_id == "default",
                    TenantModelProvider.provider_name == pname,
                )
                prov_id = prov.id
            except TenantModelProvider.DoesNotExist:
                prov_id = uuid.uuid4().hex
                TenantModelProvider.insert({
                    "id": prov_id,
                    "provider_name": pname,
                    "tenant_id": "default",
                }).execute()

            # Find or create instance row (always named "default")
            try:
                inst = TenantModelInstance.get(
                    TenantModelInstance.provider_id == prov_id,
                    TenantModelInstance.instance_name == "default",
                )
                inst_id = inst.id
            except TenantModelInstance.DoesNotExist:
                inst_id = uuid.uuid4().hex
                TenantModelInstance.insert({
                    "id": inst_id,
                    "instance_name": "default",
                    "provider_id": prov_id,
                    "api_key": entry["api_key"],
                    "status": "active",
                    "extra": "{}",
                }).execute()

            # Find or create model row
            exists = TenantModel.select().where(
                TenantModel.provider_id == prov_id,
                TenantModel.instance_id == inst_id,
                TenantModel.model_type == entry["model_type"],
                TenantModel.model_name == entry["model_name"],
            ).count()
            if not exists:
                TenantModel.insert({
                    "id": uuid.uuid4().hex,
                    "model_name": entry["model_name"],
                    "provider_id": prov_id,
                    "instance_id": inst_id,
                    "model_type": entry["model_type"],
                    "status": "active",
                    "extra": "{}",
                }).execute()

        logger.info(f"Model providers registered: {[p['provider_name'] + '/' + p['model_name'] for p in providers_to_register]}")
    except Exception as e:
        logger.warning(f"Could not register model providers: {e}")


def _migrate_embd_id_format():
    """Migrate existing KB rows from old embd_id format (model___factory)
    to new format (model@default@factory) required by the refactored task executor.
    Additionally, auto-heals any KB using an unsupported embedding model factory (e.g. BAAI)
    to the active embedding model configured in the .env settings.
    """
    try:
        from api.db.services.knowledgebase_service import KnowledgebaseService
        from api.core.config import settings
        from rag.llm import EmbeddingModel

        kbs = KnowledgebaseService.query(status="1")
        migrated = 0
        healed = 0
        for kb in kbs:
            embd_id = str(getattr(kb, "embd_id", "") or "")
            # Old format uses ___ separator, new format uses @
            if "___" in embd_id and "@" not in embd_id:
                parts = embd_id.split("___")
                if len(parts) == 2:
                    embd_id = f"{parts[0]}@default@{parts[1]}"
                    KnowledgebaseService.update_by_id(str(kb.id), {"embd_id": embd_id})
                    migrated += 1

            # Parse provider name and validate factory
            parts = embd_id.split("@")
            provider_name = parts[-1] if parts else ""
            if not embd_id or provider_name not in EmbeddingModel:
                new_embd = settings.active_embedding_ragflow_id
                KnowledgebaseService.update_by_id(str(kb.id), {"embd_id": new_embd})
                healed += 1
                logger.info(f"Healed KB {kb.id} embd_id: '{embd_id}' -> '{new_embd}'")

        if migrated:
            logger.info(f"Migrated {migrated} KB(s) embd_id to new @ format")
        if healed:
            logger.info(f"Healed {healed} KB(s) embd_id with unsupported factories to active embedding model")
    except Exception as e:
        logger.warning(f"Could not migrate/heal embd_id format: {e}")
