"""Rag-agent API.

POST /documents  upload a file -> text -> chunks -> bge-m3 dense + sparse vectors -> Qdrant
POST /retrieve   question -> sparse + dense search -> fused (RRF) -> bge-reranker -> top chunks
                 -> POSTed as {question, chunks} to every next agent in RAG_NEXT_AGENTS (found on the LAN)

No LLM call: the next agents answer from the question and the reranked chunks.
"""

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from qdrant_client.http.exceptions import ResponseHandlingException

from . import chunking, discovery, models, parsing, store
from .config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("rag_agent")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load both models on the main thread before serving: the first request no longer waits for them,
    # and a failed load restarts the container before any request is accepted.
    models.warm_up()
    yield


app = FastAPI(title="Rag-agent", description="Hybrid retrieval (dense + sparse) with reranking.", lifespan=lifespan)


@app.exception_handler(ResponseHandlingException)
async def _qdrant_unavailable(request: Request, exc: ResponseHandlingException) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": f"Qdrant unavailable at {settings.qdrant_url}"})


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

    embeddings = models.embed([text for _, text in chunks])
    document_id = str(uuid.uuid4())  # dashed form: Qdrant treats 32-hex strings as UUIDs and re-formats them
    store.add_chunks(document_id, name, chunks, embeddings)
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


def _send(port: int, path: str, result: dict) -> dict:
    """POST {question, chunks} to the PORT/PATH endpoint, on the machine found for it on the LAN.
    If that machine stops answering, searches again once. Returns the reply or the error."""
    endpoint = f"{port}{path}"
    url = discovery.next_agent_url(port, path)  # scans the network when no machine is known yet
    if url is None:
        return {"endpoint": endpoint, "url": None,
                "error": f"No machine in the local network has port {port} open and serves {path}"}
    try:
        try:
            res = httpx.post(url, json=result, timeout=settings.next_agent_timeout)
        except httpx.TransportError:  # machine gone or IP changed: find it again and retry once
            new_url = discovery.next_agent_url(port, path, refresh=True)
            if new_url is None:
                raise
            url = new_url
            res = httpx.post(url, json=result, timeout=settings.next_agent_timeout)
        res.raise_for_status()
    except httpx.HTTPError as e:
        log.warning("next agent %s failed: %s", url, e)
        return {"endpoint": endpoint, "url": url, "error": str(e) or type(e).__name__}
    try:
        reply = res.json()
    except ValueError:
        reply = res.text
    return {"endpoint": endpoint, "url": url, "status": res.status_code, "response": reply}


def _pass_to_next_agents(result: dict) -> list[dict]:
    """Send to every RAG_NEXT_AGENTS endpoint in parallel; one result per endpoint, in config order.
    A failing next agent never loses the retrieved chunks."""
    if not settings.next_agents:
        return []
    with ThreadPoolExecutor(max_workers=len(settings.next_agents)) as pool:
        return list(pool.map(lambda endpoint: _send(*endpoint, result), settings.next_agents))


@app.post("/retrieve")
def retrieve(req: RetrieveRequest) -> dict:
    """Returns {"question", "chunks": [{id, document_id, document_name, chunk_index, page, content, score}],
    "next_agents": [{endpoint, url, status, response} | {endpoint, url, error}, ...]}. Chunks are best
    first; score is the reranker's relevance (0..1). {question, chunks} is what the next agents receive."""
    candidates = store.hybrid_search(models.embed([req.question])[0], settings.candidates)
    if candidates:
        scores = models.rerank(req.question, [c["content"] for c in candidates])
        for candidate, score in zip(candidates, scores, strict=True):
            candidate["score"] = round(score, 4)
        candidates.sort(key=lambda c: c["score"], reverse=True)
    chunks = candidates[:req.top_k]
    log.info("retrieve %r: %d candidates -> %d chunks", req.question[:80], len(candidates), len(chunks))
    result = {"question": req.question, "chunks": chunks}
    return {**result, "next_agents": _pass_to_next_agents(result)}
