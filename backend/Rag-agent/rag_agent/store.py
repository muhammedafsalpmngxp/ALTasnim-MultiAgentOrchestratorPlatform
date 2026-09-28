"""Elasticsearch chunk store and hybrid search (BM25 keyword + dense vector)."""

from functools import lru_cache

from elasticsearch import Elasticsearch, helpers

from .config import settings

_SOURCE = ["document_id", "document_name", "chunk_index", "page", "content"]


@lru_cache
def client() -> Elasticsearch:
    return Elasticsearch(settings.es_url, request_timeout=60)


def ping() -> bool:
    return bool(client().ping())


def _exists() -> bool:
    return bool(client().indices.exists(index=settings.es_index))


def _ensure_index(dims: int) -> None:
    if not _exists():
        client().indices.create(index=settings.es_index, mappings={"properties": {
            "document_id": {"type": "keyword"},
            "document_name": {"type": "keyword"},
            "chunk_index": {"type": "integer"},
            "page": {"type": "integer"},
            "content": {"type": "text"},  # BM25
            "embedding": {"type": "dense_vector", "dims": dims, "index": True, "similarity": "cosine"},
        }})


def add_chunks(document_id: str, document_name: str, chunks: list[tuple[int | None, str]],
               vectors: list[list[float]]) -> None:
    """Index a document's (page, text) chunks with their vectors; searchable when this returns."""
    _ensure_index(len(vectors[0]))
    actions = (
        {
            "_index": settings.es_index,
            "_id": f"{document_id}_{i}",
            "_source": {"document_id": document_id, "document_name": document_name, "chunk_index": i,
                        "page": page, "content": text, "embedding": vector},
        }
        for i, ((page, text), vector) in enumerate(zip(chunks, vectors, strict=True))
    )
    helpers.bulk(client(), actions, refresh="wait_for")


def hybrid_search(question: str, vector: list[float], n: int) -> list[dict]:
    """Top `n` chunks from BM25 and from dense kNN, merged with reciprocal rank fusion."""
    if not _exists():
        return []
    es = client()
    bm25 = es.search(index=settings.es_index, query={"match": {"content": question}}, size=n, source=_SOURCE)
    dense = es.search(index=settings.es_index, size=n, source=_SOURCE, knn={
        "field": "embedding", "query_vector": vector, "k": n, "num_candidates": max(100, 5 * n)})
    return _rrf([bm25["hits"]["hits"], dense["hits"]["hits"]], n)


def _rrf(result_lists: list[list[dict]], n: int, k: int = 60) -> list[dict]:
    """Reciprocal rank fusion: a hit scores sum(1 / (k + rank)) over the lists it appears in."""
    scores: dict[str, float] = {}
    hits: dict[str, dict] = {}
    for results in result_lists:
        for rank, hit in enumerate(results, start=1):
            scores[hit["_id"]] = scores.get(hit["_id"], 0.0) + 1 / (k + rank)
            hits[hit["_id"]] = hit
    best = sorted(scores, key=scores.__getitem__, reverse=True)[:n]
    return [{"id": hit_id, **hits[hit_id]["_source"]} for hit_id in best]


def list_documents() -> list[dict]:
    if not _exists():
        return []
    res = client().search(index=settings.es_index, size=0, aggs={"docs": {
        "terms": {"field": "document_id", "size": 10000},
        "aggs": {"name": {"terms": {"field": "document_name", "size": 1}}},
    }})
    return [
        {"document_id": b["key"], "document_name": b["name"]["buckets"][0]["key"], "chunks": b["doc_count"]}
        for b in res["aggregations"]["docs"]["buckets"]
    ]


def get_chunks(document_id: str) -> list[dict]:
    if not _exists():
        return []
    res = client().search(index=settings.es_index, query={"term": {"document_id": document_id}},
                          sort=[{"chunk_index": "asc"}], size=10000, source=_SOURCE)
    return [{"id": h["_id"], **h["_source"]} for h in res["hits"]["hits"]]


def delete_document(document_id: str) -> int:
    """Delete a document's chunks; returns how many were deleted."""
    if not _exists():
        return 0
    res = client().delete_by_query(index=settings.es_index, query={"term": {"document_id": document_id}},
                                   refresh=True)
    return int(res["deleted"])
