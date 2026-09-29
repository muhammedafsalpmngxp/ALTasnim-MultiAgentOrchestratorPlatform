"""Join point after the parallel page fetches: chunk every source, then rerank against the question."""

from __future__ import annotations

import asyncio
import time

from langgraph.config import get_stream_writer

from web_search_agent.schemas import Evidence, Source
from web_search_agent.services.chunker import chunk_text
from web_search_agent.services.reranker import Candidate
from web_search_agent.services.resources import reranker
from web_search_agent.services.urls import get_domain, is_trusted
from web_search_agent.settings import get_settings
from web_search_agent.state import State
from web_search_agent.steps import StepReporter, plural, span_seconds


def _source(citation_id: int, hit: dict, page: dict | None) -> Source:
    return Source(
        citation_id=citation_id,
        title=((page or {}).get("title") or hit["title"]).strip(),
        url=hit["url"],
        domain=get_domain(hit["url"]),
        published_date=(page or {}).get("published_date") or hit.get("published_date"),
        author=(page or {}).get("author"),
    )


def _candidates(citation_id: int, source: Source, hit: dict, page: dict | None) -> list[Candidate]:
    settings = get_settings()
    if page:
        texts = chunk_text(
            page["text"],
            chunk_size=settings.chunk_size_words,
            overlap=settings.chunk_overlap_words,
            max_chunks=settings.max_chunks_per_page,
        )
        method = page["method"]
    elif hit.get("snippet", "").strip():
        texts, method = [hit["snippet"].strip()], "snippet"
    else:
        return []
    return [
        Candidate(
            text=text,
            source_key=str(citation_id),
            title=source.title,
            published_date=source.published_date,
            trusted=is_trusted(source.domain, settings.trusted_domain_list),
            payload={"citation_id": citation_id, "method": method},
        )
        for text in texts
    ]


def _renumber(evidence: list[Evidence], sources: list[Source]) -> tuple[list[Evidence], list[Source]]:
    """Keep only cited sources, numbered 1..n in rank order."""
    mapping: dict[int, int] = {}
    kept: list[Source] = []
    for item in evidence:
        if item.citation_id not in mapping:
            mapping[item.citation_id] = len(mapping) + 1
            kept.append(sources[item.citation_id - 1].model_copy(update={"citation_id": mapping[item.citation_id]}))
    return [item.model_copy(update={"citation_id": mapping[item.citation_id]}) for item in evidence], kept


def _context(evidence: list[Evidence]) -> str:
    return "\n\n".join(
        f"[{e.citation_id}] {e.title}{f' ({e.published_date})' if e.published_date else ''}\n{e.url}\n{e.content}"
        for e in evidence
    )


async def rank(state: State) -> dict:
    reporter = StepReporter(get_stream_writer())
    hits, pages = state["hits"], state.get("pages", {})
    fetched = [url for url in pages if url in {h["url"] for h in hits}]
    extracted = sum(1 for url in fetched if pages[url])
    warnings = []
    if extracted < len(fetched):
        warnings.append(f"extracted {extracted}/{len(fetched)} pages; used search snippets for the rest")
    if fetched:
        steps = reporter.report(
            "extract", "done", f"{extracted}/{len(fetched)} pages extracted with Trafilatura",
            [f"{'ok' if pages[url] else 'snippet'}  {get_domain(url)}" for url in fetched],
            duration_s=span_seconds(state.get("spans", {}), "extract"),
        )
    else:
        steps = reporter.report("extract", "skipped", "Sample data - no pages to download, using the snippets")
    # Sample data only: BM25 is enough, and the cross-encoder (a ~1 GB download) is never loaded.
    live = any(hit.get("provider") != "sample" for hit in hits)

    # Chunk
    started = time.time()
    reporter.report("chunk", "running", "Splitting pages into passages")
    sources: list[Source] = []
    candidates: list[Candidate] = []
    for citation_id, hit in enumerate(hits, start=1):
        page = pages.get(hit["url"])
        source = _source(citation_id, hit, page)
        sources.append(source)
        candidates.extend(_candidates(citation_id, source, hit, page))
    steps.update(reporter.report(
        "chunk", "done", f"{plural(len(candidates), 'passage')} from {plural(len(hits), 'source')}",
        duration_s=time.time() - started,
    ))

    # Rerank (CPU/GPU bound -> thread)
    started = time.time()
    model = reranker()
    reporter.report("rerank", "running", f"Scoring {plural(len(candidates), 'passage')}")
    ranked = await asyncio.to_thread(model.rerank, state["query"], candidates, state.get("top_k") or 5, live)
    reranker_name = model.active_name if live else "bm25"
    evidence = []
    for position, item in enumerate(ranked, start=1):
        source = sources[item.candidate.payload["citation_id"] - 1]
        evidence.append(Evidence(
            rank=position,
            citation_id=source.citation_id,
            title=source.title,
            url=source.url,
            domain=source.domain,
            published_date=source.published_date,
            content=item.candidate.text,
            relevance_score=round(item.relevance, 4),
            final_score=round(item.final_score, 4),
            extraction_method=item.candidate.payload["method"],
        ))
    evidence, sources = _renumber(evidence, sources)
    steps.update(reporter.report(
        "rerank", "done", f"{len(candidates)} -> {plural(len(evidence), 'passage')} ({reranker_name})",
        [f"{e.relevance_score:.2f}  {e.domain}" for e in evidence],
        duration_s=time.time() - started,
    ))

    return {
        "evidence": [e.model_dump() for e in evidence],
        "sources": [s.model_dump() for s in sources],
        "context": _context(evidence),
        "reranker": reranker_name,
        "warnings": warnings,
        "step_state": steps,
    }
