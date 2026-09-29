"""Hybrid reranker.

Stage 1  BM25 prefilter        cheap lexical recall, trims the pool sent to the cross-encoder
Stage 2  Cross-encoder         reads (query, passage) together -> precise relevance
                               (default cross-encoder/ms-marco-MiniLM-L-6-v2; WEB_SEARCH_RERANKER_MODEL)
Stage 3  Recency, trust,       blends in publish date and a boost for trusted sources (WEB_SEARCH_TRUSTED_DOMAINS),
         diversity             caps chunks per source

The model is downloaded once into ``backend/web_search_agent/models/<name>`` (WEB_SEARCH_RERANKER_DIR) and always
loaded from there: no Hugging Face update checks on every start, works offline after the first run.

If the cross-encoder cannot be loaded (no torch, offline, ...) BM25 scores are used instead,
so the agent keeps working in a degraded mode.
"""

import logging
import math
import re
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

from rank_bm25 import BM25Okapi

from web_search_agent.settings import Settings

logger = logging.getLogger(__name__)

AGENT_DIR = Path(__file__).resolve().parents[3]  # backend/web_search_agent
# The files a cross-encoder needs (skips ONNX / OpenVINO copies and the duplicate pytorch_model.bin)
_MODEL_FILES = ["*.json", "*.safetensors", "*.txt", "*.model", "sentencepiece*"]
_TOKEN = re.compile(r"\w+", re.UNICODE)


@dataclass
class Candidate:
    text: str
    source_key: str  # chunks with the same key come from the same page
    title: str = ""
    published_date: str | None = None
    trusted: bool = False  # from a WEB_SEARCH_TRUSTED_DOMAINS site: gets the trusted boost
    payload: object = None  # opaque data carried through for the caller


@dataclass
class ScoredCandidate:
    candidate: Candidate
    relevance: float
    final_score: float


def _tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def _parse_date(value: str | None) -> datetime | None:
    """Accepts ISO 8601 (Trafilatura, SearXNG) and RFC 2822 (Tavily news) dates."""
    if not value:
        return None
    value = value.strip()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None


class Reranker:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._model = None
        self._load_error: str | None = None
        self._load_attempted = False
        self._load_lock = threading.Lock()
        self._predict_lock = threading.Lock()

    # --- model lifecycle -------------------------------------------------------
    @property
    def model_name(self) -> str:
        return self._settings.reranker_model

    @property
    def loaded(self) -> bool:
        return self._model is not None

    @property
    def load_error(self) -> str | None:
        return self._load_error

    @property
    def active_name(self) -> str:
        return self.model_name if self.loaded else "bm25"

    def local_path(self) -> str:
        """The model's folder in WEB_SEARCH_RERANKER_DIR, downloaded there the first time (a path is used as is)."""
        if Path(self.model_name).is_dir():
            return self.model_name
        folder = Path(self._settings.reranker_dir or AGENT_DIR / "models") / self.model_name.replace("/", "--")
        if not (folder / "config.json").is_file():
            from huggingface_hub import snapshot_download

            logger.info("Downloading reranker %s once into %s", self.model_name, folder)
            snapshot_download(repo_id=self.model_name, local_dir=str(folder), allow_patterns=_MODEL_FILES)
        return str(folder)

    def load(self, wait: bool = True) -> None:
        """Load the cross-encoder once. With wait=False, returns immediately if another thread is loading."""
        if self._load_attempted or not self._load_lock.acquire(blocking=wait):
            return
        try:
            if self._load_attempted:
                return
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(
                self.local_path(),
                max_length=self._settings.reranker_max_length,
                device=self._settings.reranker_device,
            )
            logger.info("Reranker loaded: %s", self.model_name)
        except Exception as exc:  # noqa: BLE001
            self._load_error = f"{type(exc).__name__}: {exc}"
            logger.warning("Cross-encoder unavailable, falling back to BM25: %s", self._load_error)
        finally:
            self._load_attempted = True
            self._load_lock.release()

    # --- ranking ---------------------------------------------------------------
    def rerank(
        self, query: str, candidates: list[Candidate], top_k: int, cross_encoder: bool = True
    ) -> list[ScoredCandidate]:
        """Blocking (CPU/GPU bound) - call via asyncio.to_thread. ``cross_encoder=False``: BM25 only."""
        if not candidates:
            return []
        if cross_encoder:
            # Loads on first use if not preloaded; while a (pre)load is still running, BM25 is used instead.
            self.load(wait=False)
        use_model = cross_encoder and self.loaded

        pool = self._bm25_prefilter(query, candidates, self._settings.rerank_candidate_pool)
        relevance = self._cross_encode(query, pool) if use_model else self._bm25_scores(query, pool)

        weight = min(max(self._settings.recency_weight, 0.0), 1.0)
        boost = max(self._settings.trusted_boost, 0.0)
        scored = [
            ScoredCandidate(
                candidate=candidate,
                relevance=rel,
                final_score=min(1.0, (1 - weight) * rel + weight * self._recency(candidate.published_date)
                                + (boost if candidate.trusted else 0.0)),
            )
            for candidate, rel in zip(pool, relevance, strict=True)
        ]
        scored.sort(key=lambda item: item.final_score, reverse=True)

        threshold = self._settings.min_relevance_score if use_model else 0.0
        per_source: dict[str, int] = {}
        selected = []
        for item in scored:
            if item.relevance < threshold:
                continue
            key = item.candidate.source_key
            if per_source.get(key, 0) >= self._settings.max_chunks_per_source:
                continue
            per_source[key] = per_source.get(key, 0) + 1
            selected.append(item)
            if len(selected) >= top_k:
                break
        return selected

    def _bm25_scores(self, query: str, candidates: list[Candidate]) -> list[float]:
        corpus = [_tokenize(f"{c.title} {c.text}") for c in candidates]
        if not any(corpus):
            return [0.0] * len(candidates)
        scores = BM25Okapi(corpus).get_scores(_tokenize(query))
        top = max(scores) if len(scores) else 0.0
        return [float(s / top) if top > 0 else 0.0 for s in scores]

    def _bm25_prefilter(self, query: str, candidates: list[Candidate], limit: int) -> list[Candidate]:
        if len(candidates) <= limit:
            return candidates
        scores = self._bm25_scores(query, candidates)
        ranked = sorted(zip(candidates, scores, strict=True), key=lambda pair: pair[1], reverse=True)
        return [candidate for candidate, _ in ranked[:limit]]

    def _cross_encode(self, query: str, candidates: list[Candidate]) -> list[float]:
        pairs = [(query, f"{c.title}\n{c.text}" if c.title else c.text) for c in candidates]
        with self._predict_lock:  # one batch at a time; parallel batches just thrash the CPU
            raw = self._model.predict(
                pairs, batch_size=self._settings.reranker_batch_size, show_progress_bar=False
            )
        scores = [float(s) for s in raw]
        # Some models/versions return logits; squash to 0-1 so thresholds are comparable.
        if any(s < 0.0 or s > 1.0 for s in scores):
            scores = [1.0 / (1.0 + math.exp(-s)) for s in scores]
        return scores

    def _recency(self, published: str | None) -> float:
        date = _parse_date(published)
        if date is None:
            return 0.5  # unknown date: neutral
        if date.tzinfo is None:
            date = date.replace(tzinfo=UTC)
        age_days = max((datetime.now(UTC) - date).total_seconds() / 86400, 0.0)
        return 0.5 ** (age_days / self._settings.recency_half_life_days)
