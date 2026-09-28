"""Rag-agent API.

POST /documents  upload a file -> text -> chunks -> bge-m3 vectors -> Elasticsearch
POST /retrieve   question -> BM25 + dense search -> fused -> bge-reranker -> top chunks

No LLM call: the question and the reranked chunks are returned for the next agent to answer from.
"""

import logging
import uuid

from elasticsearch import ConnectionError as ESConnectionError
from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import chunking, models, parsing, store
from .config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("rag_agent")

app = FastAPI(title="Rag-agent", description="Hybrid retrieval (BM25 + dense) with reranking.")


@app.exception_handler(ESConnectionError)
async def _es_unavailable(request: Request, exc: ESConnectionError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": f"Elasticsearch unavailable at {settings.es_url}"})


class RetrieveRequest(BaseModel):
    question: str = Field(min_length=1)
    top_k: int = Field(default=settings.top_k, ge=1, le=50)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/documents", status_code=201)
def upload_document(file: UploadFile) -> dict:
    name = file.filename or "upload"
    data = file.file.read()
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File is larger than {settings.max_upload_mb} MB")
    try:
        sections = parsing.extract_sections(name, data)
    except parsing.UnsupportedFileType as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    chunks = [
        (page, chunk)
        for page, text in sections
        for chunk in chunking.chunk_text(text, settings.chunk_words, settings.chunk_overlap_words)
    ]
    if not chunks:
        raise HTTPException(status_code=422, detail="No text found in the file (scanned PDFs need OCR, not supported)")

    vectors = models.embed([text for _, text in chunks])
    document_id = uuid.uuid4().hex
    store.add_chunks(document_id, name, chunks, vectors)
    log.info("indexed %s (%s): %d chunks", name, document_id, len(chunks))
    return {"document_id": document_id, "document_name": name, "chunks": len(chunks)}


@app.get("/documents")
def list_documents() -> list[dict]:
    return store.list_documents()


@app.get("/documents/{document_id}/chunks")
def document_chunks(document_id: str) -> list[dict]:
    chunks = store.get_chunks(document_id)
    if not chunks:
        raise HTTPException(status_code=404, detail="Document not found")
    return chunks


@app.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: str) -> None:
    if not store.delete_document(document_id):
        raise HTTPException(status_code=404, detail="Document not found")


@app.post("/retrieve")
def retrieve(req: RetrieveRequest) -> dict:
    """Returns {"question", "chunks": [{id, document_id, document_name, chunk_index, page, content, score}]},
    best first; score is the reranker's relevance (0..1)."""
    vector = models.embed([req.question])[0]
    candidates = store.hybrid_search(req.question, vector, settings.candidates)
    if candidates:
        scores = models.rerank(req.question, [c["content"] for c in candidates])
        for candidate, score in zip(candidates, scores, strict=True):
            candidate["score"] = round(score, 4)
        candidates.sort(key=lambda c: c["score"], reverse=True)
    chunks = candidates[:req.top_k]
    log.info("retrieve %r: %d candidates -> %d chunks", req.question[:80], len(candidates), len(chunks))
    return {"question": req.question, "chunks": chunks}
