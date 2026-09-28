"""Qdrant chunk store and hybrid search: dense + sparse vectors, fused with RRF inside Qdrant."""

import uuid
from functools import lru_cache

from qdrant_client import QdrantClient
from qdrant_client import models as qm

from .config import settings
from .models import Embedding


@lru_cache
def client() -> QdrantClient:
    return QdrantClient(url=settings.qdrant_url, timeout=60)


def _exists() -> bool:
    return client().collection_exists(settings.qdrant_collection)


def _ensure_collection(dims: int) -> None:
    if not _exists():
        client().create_collection(
            settings.qdrant_collection,
            vectors_config={"dense": qm.VectorParams(size=dims, distance=qm.Distance.COSINE)},
            sparse_vectors_config={"sparse": qm.SparseVectorParams()},
        )
        client().create_payload_index(settings.qdrant_collection, "document_id", qm.PayloadSchemaType.KEYWORD)


def _sparse(weights: dict[int, float]) -> qm.SparseVector:
    return qm.SparseVector(indices=list(weights), values=list(weights.values()))


def _of_document(document_id: str) -> qm.Filter:
    return qm.Filter(must=[qm.FieldCondition(key="document_id", match=qm.MatchValue(value=document_id))])


def _chunk(point) -> dict:
    return {"id": str(point.id), **point.payload}


def add_chunks(document_id: str, document_name: str, chunks: list[tuple[int | None, str]],
               embeddings: list[Embedding]) -> None:
    """Store a document's (page, text) chunks with their vectors; searchable when this returns."""
    _ensure_collection(len(embeddings[0].dense))
    points = [
        qm.PointStruct(
            id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{document_id}/{i}")),
            vector={"dense": e.dense, "sparse": _sparse(e.sparse)},
            payload={"document_id": document_id, "document_name": document_name, "chunk_index": i,
                     "page": page, "content": text},
        )
        for i, ((page, text), e) in enumerate(zip(chunks, embeddings, strict=True))
    ]
    client().upload_points(settings.qdrant_collection, points, batch_size=64, wait=True)


def hybrid_search(question: Embedding, n: int) -> list[dict]:
    """Top `n` chunks by sparse (keyword) and by dense similarity, fused with reciprocal rank fusion."""
    if not _exists():
        return []
    prefetch = [qm.Prefetch(query=question.dense, using="dense", limit=n)]
    if question.sparse:
        prefetch.append(qm.Prefetch(query=_sparse(question.sparse), using="sparse", limit=n))
    res = client().query_points(settings.qdrant_collection, prefetch=prefetch,
                                query=qm.FusionQuery(fusion=qm.Fusion.RRF), limit=n, with_payload=True)
    return [_chunk(p) for p in res.points]


def list_documents() -> list[dict]:
    if not _exists():
        return []
    docs = []
    for hit in client().facet(settings.qdrant_collection, key="document_id", limit=10000, exact=True).hits:
        [first], _ = client().scroll(settings.qdrant_collection, scroll_filter=_of_document(hit.value), limit=1,
                                     with_payload=["document_name"])
        docs.append({"document_id": hit.value, "document_name": first.payload["document_name"], "chunks": hit.count})
    return docs


def get_chunks(document_id: str) -> list[dict]:
    if not _exists():
        return []
    points, _ = client().scroll(settings.qdrant_collection, scroll_filter=_of_document(document_id), limit=10000,
                                with_payload=True)
    return sorted((_chunk(p) for p in points), key=lambda c: c["chunk_index"])


def delete_document(document_id: str) -> int:
    """Delete a document's chunks; returns how many were deleted."""
    if not _exists():
        return 0
    count = client().count(settings.qdrant_collection, count_filter=_of_document(document_id), exact=True).count
    if count:
        client().delete(settings.qdrant_collection, points_selector=qm.FilterSelector(filter=_of_document(document_id)),
                        wait=True)
    return count
