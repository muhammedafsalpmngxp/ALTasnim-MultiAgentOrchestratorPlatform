"""Deployment settings of the web-search-agent.

Every variable is prefixed ``WEB_SEARCH_`` (e.g. ``WEB_SEARCH_TAVILY_API_KEY``). Where they are read from, first wins:

1. real environment variables (Docker, CI, the shell)
2. ``backend/web_search_agent/.env``  - this agent's own file (``WEB_SEARCH_ENV_FILE`` points elsewhere)
3. ``backend/.env``                   - the platform's shared file, section ``web-search-agent`` (``utils.env``)

The defaults run fully offline (``WEB_SEARCH_PROVIDERS=sample``, no LLM), like the rest of the platform.
Per-run knobs live in ``context.py``; per-step inputs from the supervisor in ``card.WebSearchParams``.
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

from dotenv import dotenv_values
from pydantic_settings import BaseSettings, SettingsConfigDict

from utils.env import BACKEND_ROOT, load_env

ENV_PREFIX = "WEB_SEARCH_"
# backend/web_search_agent/src/web_search_agent/settings.py -> parents[2] == backend/web_search_agent/
AGENT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def load_agent_env() -> None:
    """Load this agent's own ``.env``. Its values win over ``backend/.env`` but never over real env variables.

    Skipped under pytest (unless ``WEB_SEARCH_ENV_FILE`` is set), so tests never use your live keys or call the
    verifier machine - the orchestrator's tests run this graph in-process too.
    """
    explicit = os.getenv(f"{ENV_PREFIX}ENV_FILE")
    if not explicit and "pytest" in sys.modules:
        return
    path = Path(explicit or AGENT_ENV_FILE)
    if not path.is_file():
        return
    shared_file = Path(os.getenv("ENV_FILE", BACKEND_ROOT / ".env"))
    shared = dotenv_values(shared_file) if shared_file.is_file() else {}
    for key, value in dotenv_values(path).items():
        if value is None:
            continue
        current = os.environ.get(key)
        # unset, or only set because utils.env loaded the same value from backend/.env
        if current is None or (key in shared and current == shared[key]):
            os.environ[key] = value


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX, extra="ignore")

    agent_id: str = "web_search"

    # --- Search providers, tried in order until one returns results ----------------
    # sample = offline placeholder data (default) | live: google,tavily,searxng,duckduckgo
    providers: str = "sample"
    tavily_api_key: str | None = None
    # Google Programmable Search (free: 100 queries/day): an API key + a search engine id ("cx")
    google_api_key: str | None = None
    google_cse_id: str | None = None
    searxng_url: str | None = None  # e.g. http://localhost:8080 (JSON format must be enabled)
    # Searched on every query too, merged with the results above (live providers only): wikipedia | empty
    always_providers: str = "wikipedia"
    always_results_per_query: int = 2  # e.g. the 2 best Wikipedia articles
    wikipedia_language: str = "en"
    search_results_per_query: int = 5
    max_total_results: int = 8  # after merging the planned queries
    # Never used as sources (social media, video, forums); a domain matches its subdomains too
    blocked_domains: str = ("facebook.com,instagram.com,tiktok.com,x.com,twitter.com,youtube.com,pinterest.com,"
                            "linkedin.com,reddit.com,quora.com,threads.net,snapchat.com")
    # Preferred: ranked higher and read first. "gov" / "edu" = any government / university domain (gov.in, ...)
    trusted_domains: str = ("wikipedia.org,britannica.com,reuters.com,apnews.com,bbc.com,bbc.co.uk,who.int,un.org,"
                            "gov,edu")
    trusted_boost: float = 0.15  # added to a trusted source's rerank score (0-1)
    search_timeout_seconds: float = 10.0
    search_cache_ttl_seconds: int = 900

    # --- Page fetching (httpx + Trafilatura) --------------------------------------
    max_pages_to_fetch: int = 4
    max_concurrent_fetches: int = 6
    fetch_timeout_seconds: float = 8.0
    page_deadline_seconds: float = 8.0  # hard cap per page (robots.txt + download + extraction)
    min_extracted_chars: int = 200
    respect_robots_txt: bool = True
    use_playwright_fallback: bool = False
    page_cache_ttl_seconds: int = 3600
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0 Safari/537.36 WebSearchAgent/2.0"
    )

    # --- Chunking ------------------------------------------------------------------
    chunk_size_words: int = 220
    chunk_overlap_words: int = 40
    max_chunks_per_page: int = 12

    # --- Reranking (BM25 prefilter -> cross-encoder -> recency + diversity) --------
    # cross-encoder/ms-marco-MiniLM-L-6-v2: 90 MB, ~4x faster than BAAI/bge-reranker-base (1.1 GB) on CPU, same top
    # results on real runs. Downloaded once into reranker_dir and loaded from there (no Hugging Face checks).
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    reranker_dir: str = ""  # default: backend/web_search_agent/models
    reranker_device: str | None = None
    reranker_max_length: int = 512
    reranker_batch_size: int = 16
    reranker_preload: bool = True
    rerank_candidate_pool: int = 40
    recency_weight: float = 0.1
    recency_half_life_days: float = 30.0
    max_chunks_per_source: int = 2
    min_relevance_score: float = 0.05

    # --- LLM (OpenAI via langchain-openai) -----------------------------------------
    openai_api_key: str | None = None  # empty = no query planning; the question is searched as-is
    openai_base_url: str | None = None
    openai_fast_model: str = "gpt-4o-mini"
    openai_timeout_seconds: float = 90.0
    query_planning: bool = True
    max_search_queries: int = 3

    # --- Step result for the orchestrator / verifier: the question + the best N passages -----
    result_top_n: int = 3

    # --- Send the output (question + top 3 contents) to other agents over plain HTTP ----------------
    # The POST routes to send it to, e.g. "/verify,/synthesize". Every machine of the network that has one of them
    # on the port below gets the output (one POST per route found). Empty = send nothing.
    verifier_path: str = ""
    verifier_port: str = "8203"  # one port or several: "8203,8230"
    verifier_token: str | None = None  # sent as "Authorization: Bearer ..." if set
    verifier_timeout_seconds: float = 120.0  # e.g. a synthesizer writes an answer with an LLM
    # Network discovery
    discovery_subnets: str = ""  # e.g. "192.168.1.0/24,10.0.0.0/24"; default: the /24 of this machine's IPs
    discovery_scan_timeout_seconds: float = 2.0  # per-host connect timeout (Wi-Fi connects can take > 1 s)
    discovery_attempts: int = 2  # tries per host, so a flapping link is still found
    send_attempts: int = 3  # tries per POST on connection errors, before searching the network again
    discovery_ttl_seconds: float = 600  # how long found routes are reused

    # --- Saved runs: "Retry" sends a run's output again from here (no search, no LLM) ---------------------
    checkpoint_dir: str = ""  # default: backend/web_search_agent/logs/checkpoints
    checkpoint_keep: int = 200  # newest checkpoints kept

    # --- UI history (/custom/history, /custom/sources) -------------------------------
    history_size: int = 50

    @property
    def provider_order(self) -> list[str]:
        return [name.lower() for name in _split_csv(self.providers)]

    @property
    def always_provider_order(self) -> list[str]:
        return [name.lower() for name in _split_csv(self.always_providers)]

    @property
    def blocked_domain_list(self) -> list[str]:
        return [d.lower() for d in _split_csv(self.blocked_domains)]

    @property
    def trusted_domain_list(self) -> list[str]:
        return [d.lower() for d in _split_csv(self.trusted_domains)]

    @property
    def offline(self) -> bool:
        """Only the sample provider: no page fetching and no cross-encoder download."""
        return self.provider_order in ([], ["sample"])

    @property
    def output_paths(self) -> list[str]:
        """The POST routes to send the output to, normalised ("/verify"), in order."""
        paths = ["/" + p.strip().strip("/") for p in _split_csv(self.verifier_path) if p.strip().strip("/")]
        return list(dict.fromkeys(paths))

    @property
    def output_ports(self) -> list[int]:
        return list(dict.fromkeys(int(p) for p in _split_csv(str(self.verifier_port)))) or [8203]

    @property
    def llm_configured(self) -> bool:
        return bool(self.openai_api_key)


@lru_cache
def get_settings() -> Settings:
    load_env()  # backend/.env (no-op if utils already loaded it)
    load_agent_env()  # backend/web_search_agent/.env
    return Settings()
