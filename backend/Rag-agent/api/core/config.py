import os
from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parents[2] / ".env"),  # backend/.env
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────
    APP_NAME: str = "LT Files Assistant"
    APP_VERSION: str = "1.0.0"
    APP_ENV: str = "development"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 9380
    DEBUG: bool = True

    # ── Auth ─────────────────────────────────────────────
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "Lt@Assistant2024"
    ADMIN_EMAIL: str = "admin@lt-assistant.com"
    JWT_SECRET_KEY: str = "change-this-to-a-random-32-character-string"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRY_HOURS: int = 24

    # ── Database ─────────────────────────────────────────
    # LT_DB_TYPE avoids collision with RAGFlow's own DB_TYPE env var
    LT_DB_TYPE: str = "sqlite"        # sqlite | mysql | postgresql
    DB_TYPE: str = "sqlite"           # kept for backwards compat — use LT_DB_TYPE
    DB_PATH: str = "./data/lt_assistant.db"
    DB_HOST: str = "localhost"
    DB_PORT: int = 3306
    DB_NAME: str = "lt_assistant"
    DB_USER: str = "root"
    DB_PASSWORD: str = ""

    # ── LLM Provider ─────────────────────────────────────
    LLM_PROVIDER: str = "openai"      # openai | groq | gemini | local
    LLM_MAX_TOKENS: int = 4096
    LLM_TEMPERATURE: float = 0.1

    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o"
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"

    # Groq
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    # Gemini
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.0-flash"

    # Local (Ollama)
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.2"

    # ── Embedding ────────────────────────────────────────
    # EMBEDDING_PROVIDER: openai | bge | local
    #   openai → text-embedding-3-small via OpenAI API (paid)
    #   bge    → BAAI/bge-m3 via BAAI API (free)
    #   local  → BAAI/bge-m3 via Ollama (free, runs on your machine)
    EMBEDDING_PROVIDER: str = "openai"
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"
    BGE_EMBEDDING_MODEL: str = "BAAI/bge-m3"
    LOCAL_EMBEDDING_MODEL: str = "BAAI/bge-m3"

    # ── Reranking ────────────────────────────────────────
    # RERANK_PROVIDER: bge | local | "" (disabled)
    #   bge   → BAAI/bge-reranker-v2-m3 via BAAI API (free, no API key needed)
    #   local → BAAI/bge-reranker-v2-m3 via Ollama (free, runs on your machine)
    #   ""    → reranking disabled
    RERANK_PROVIDER: str = ""
    BGE_RERANK_MODEL: str = "BAAI/bge-reranker-v2-m3"
    LOCAL_RERANK_MODEL: str = "BAAI/bge-reranker-v2-m3"

    # ── Search Engine ────────────────────────────────────
    DOC_ENGINE: str = "elasticsearch"    # elasticsearch | infinity
    ES_HOST: str = "http://localhost:9200"
    ES_USER: str = ""
    ES_PASSWORD: str = ""

    # ── Redis ────────────────────────────────────────────
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""
    REDIS_DB: int = 0

    # ── Storage ──────────────────────────────────────────
    STORAGE_TYPE: str = "local"          # local | minio
    STORAGE_PATH: str = "./data/files"
    MINIO_HOST: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET: str = "lt-files"
    MINIO_SECURE: bool = False

    # ── File Processing ──────────────────────────────────
    MAX_UPLOAD_SIZE_MB: int = 500
    SUPPORTED_EXTENSIONS: str = "pdf,docx,doc,xlsx,xls,pptx,ppt,txt,md,html,json,png,jpg,jpeg,bmp,tiff,dwg,dxf,eml,msg,mp3,wav,m4a,epub,csv"
    DWG_AUTO_CONVERT: bool = True
    LIBREOFFICE_PATH: str = "libreoffice"

    # ── CORS ─────────────────────────────────────────────
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    @property
    def active_embedding_model(self) -> str:
        p = self.EMBEDDING_PROVIDER.lower()
        if p == "openai":
            return self.OPENAI_EMBEDDING_MODEL
        if p in ("bge", "local"):
            return self.BGE_EMBEDDING_MODEL     # BAAI/bge-m3
        return self.OPENAI_EMBEDDING_MODEL

    @property
    def active_embedding_factory(self) -> str:
        p = self.EMBEDDING_PROVIDER.lower()
        if p == "openai":
            return "OpenAI"
        if p in ("bge", "local"):
            return "LocalHF"                    # LocalHuggingFaceEmbed (FlagEmbedding, free, local)
        return "OpenAI"

    @property
    def active_embedding_ragflow_id(self) -> str:
        return f"{self.active_embedding_model}@default@{self.active_embedding_factory}"

    @property
    def active_rerank_model(self) -> str:
        p = self.RERANK_PROVIDER.lower()
        if p in ("bge", "local"):
            return self.BGE_RERANK_MODEL
        return ""

    @property
    def active_rerank_factory(self) -> str:
        p = self.RERANK_PROVIDER.lower()
        if p in ("bge", "local"):
            return "LocalHF"
        return ""

    @property
    def active_rerank_ragflow_id(self) -> str:
        if not self.active_rerank_model:
            return ""
        return f"{self.active_rerank_model}@default@{self.active_rerank_factory}"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",")]

    @property
    def supported_extensions_list(self) -> list[str]:
        return [e.strip().lower() for e in self.SUPPORTED_EXTENSIONS.split(",")]

    def llm_model_for(self, provider: str) -> str:
        mapping = {
            "openai": self.OPENAI_MODEL,
            "groq": self.GROQ_MODEL,
            "gemini": self.GEMINI_MODEL,
            "local": self.OLLAMA_MODEL,
        }
        return mapping.get(provider, self.OPENAI_MODEL)

    def llm_api_key_for(self, provider: str) -> str:
        mapping = {
            "openai": self.OPENAI_API_KEY,
            "groq": self.GROQ_API_KEY,
            "gemini": self.GEMINI_API_KEY,
            "local": "ollama",
        }
        return mapping.get(provider, "")

    # The active_llm_* properties describe the .env default (LLM_PROVIDER). The provider actually
    # in use can be overridden at runtime by an admin — see api/core/llm_provider.py.
    @property
    def active_llm_model(self) -> str:
        return self.llm_model_for(self.LLM_PROVIDER)

    @property
    def active_llm_api_key(self) -> str:
        return self.llm_api_key_for(self.LLM_PROVIDER)

    @property
    def active_llm_base_url(self) -> str | None:
        if self.LLM_PROVIDER == "local":
            return f"{self.OLLAMA_BASE_URL}/v1"
        if self.LLM_PROVIDER == "openai" and self.OPENAI_BASE_URL != "https://api.openai.com/v1":
            return self.OPENAI_BASE_URL
        return None


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
