"""Rag-agent API.

POST /documents  upload a file -> text -> chunks -> bge-m3 dense + sparse vectors -> Qdrant
POST /retrieve   question -> sparse + dense search -> fused (RRF) -> bge-reranker -> top chunks
                 -> POSTed as {question, chunks} to every next agent in RAG_NEXT_AGENTS (found on the LAN)
POST /next-agents/retry  send {question, chunks} again to one of those next agents (e.g. after it failed)

POST /documents/stream and /retrieve/stream do the same, reporting each step as it happens (NDJSON, for the UI).
GET  /card       what this agent does, for the supervisor's planning

No LLM call: the next agents answer from the question and the reranked chunks. The supervisor runs the
LangGraph graph instead (graph.py, served with these routes by `langgraph dev`): the same retrieve, and the
supervisor routes the result, so nothing is passed to RAG_NEXT_AGENTS.
"""

import json
import logging
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from qdrant_client.http.exceptions import ResponseHandlingException

from . import chunking, discovery, models, parsing, store
from .config import parse_endpoints, settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("rag_agent")
EMBED_SLICE = 16  # chunks embedded per progress step (= the model batch size, so no slower)


def _count(n: int, word: str) -> str:
    return f"{n:,} {word}{'' if n == 1 else 's'}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load both models on the main thread before serving: the first request no longer waits for them,
    # and a failed load restarts the container before any request is accepted.
    models.warm_up()
    yield


app = FastAPI(title="Rag-agent", description="Hybrid retrieval (dense + sparse) with reranking.", lifespan=lifespan)


def _qdrant_detail() -> str:
    return f"Qdrant unavailable at {settings.qdrant_url}"


@app.exception_handler(ResponseHandlingException)
async def _qdrant_unavailable(request: Request, exc: ResponseHandlingException) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": _qdrant_detail()})


class RetrieveRequest(BaseModel):
    question: str = Field(min_length=1)
    top_k: int = Field(default=settings.top_k, ge=1, le=50)


class RetryRequest(BaseModel):
    endpoint: str = Field(description="One of RAG_NEXT_AGENTS, e.g. 8204/synthesize")
    question: str = Field(min_length=1)
    chunks: list[dict]


# ------------------------------------------------------------------------------------------------ steps
# Upload and retrieve are generators of step events, so the same code serves the JSON endpoints (run to the end)
# and the /stream endpoints (every event sent as it happens):
#   {"plan": [step ids]}                                   first: the steps this run will take
#   {"step": id, "state": "start" | "progress" | "done", "detail"?: str, "progress"?: [done, total], ...}
#   {"result": {...}}                                      last: what the JSON endpoint returns
Steps = Iterator[dict]


def _run(steps: Steps) -> dict:
    """The JSON endpoints: run all steps; errors raise as usual (HTTPException -> its status code)."""
    result: dict = {}
    for event in steps:
        result = event.get("result", result)
    return result


def _stream(steps: Steps) -> StreamingResponse:
    """The /stream endpoints: one JSON line per event. An error after the response started can't change the
    status code, so it is the last line instead: {"error": {"status", "detail"}}."""

    def lines() -> Iterator[str]:
        try:
            for event in steps:
                yield json.dumps(event, default=str) + "\n"
        except HTTPException as e:
            yield json.dumps({"error": {"status": e.status_code, "detail": e.detail}}) + "\n"
        except ResponseHandlingException:
            yield json.dumps({"error": {"status": 503, "detail": _qdrant_detail()}}) + "\n"
        except Exception:
            log.exception("streamed request failed")
            yield json.dumps({"error": {"status": 500, "detail": "Internal error (see the Rag-agent logs)"}}) + "\n"

    # a sync iterator: Starlette runs it in a worker thread, so the model calls don't block other requests
    return StreamingResponse(lines(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _upload_steps(name: str, data: bytes) -> Steps:
    yield {"plan": ["read", "chunk", "embed", "store"]}

    yield {"step": "read", "state": "start"}
    try:
        sections = parsing.extract_sections(name, data)
    except parsing.UnsupportedFileType as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    pages = sum(1 for page, _ in sections if page)
    words = sum(len(text.split()) for _, text in sections)
    detail = f"{_count(pages, 'page')} · {_count(words, 'word')}" if pages else _count(words, "word")
    yield {"step": "read", "state": "done", "detail": detail}

    yield {"step": "chunk", "state": "start"}
    chunks = [
        (page, chunk)
        for page, text in sections
        for chunk in chunking.chunk_text(text, settings.chunk_words, settings.chunk_overlap_words)
    ]
    if not chunks:
        raise HTTPException(status_code=422, detail="No text found in the file (scanned PDFs need OCR, not supported)")
    yield {"step": "chunk", "state": "done", "detail": _count(len(chunks), "chunk")}

    texts = [text for _, text in chunks]
    yield {"step": "embed", "state": "start", "progress": [0, len(texts)]}
    embeddings: list[models.Embedding] = []
    for start in range(0, len(texts), EMBED_SLICE):
        embeddings += models.embed(texts[start:start + EMBED_SLICE])
        yield {"step": "embed", "state": "progress", "progress": [len(embeddings), len(texts)]}
    yield {"step": "embed", "state": "done", "detail": _count(len(embeddings), "dense + sparse vector")}

    yield {"step": "store", "state": "start"}
    document_id = str(uuid.uuid4())  # dashed form: Qdrant treats 32-hex strings as UUIDs and re-formats them
    store.add_chunks(document_id, name, chunks, embeddings)
    yield {"step": "store", "state": "done", "detail": "saved in Qdrant"}
    log.info("indexed %s (%s): %d chunks", name, document_id, len(chunks))
    yield {"result": {"document_id": document_id, "document_name": name, "chunks": len(chunks)}}


def _retrieve_steps(req: RetrieveRequest, forward: bool = True) -> Steps:
    """``forward``: pass {question, chunks} to RAG_NEXT_AGENTS (the graph does not: the supervisor routes)."""
    send = forward and bool(settings.next_agents)
    yield {"plan": ["embed", "search", "rerank"] + (["send"] if send else [])}

    yield {"step": "embed", "state": "start"}
    query = models.embed([req.question])[0]
    yield {"step": "embed", "state": "done", "detail": "dense + sparse"}

    yield {"step": "search", "state": "start"}
    candidates = store.hybrid_search(query, settings.candidates)
    yield {"step": "search", "state": "done", "detail": _count(len(candidates), "candidate")}

    yield {"step": "rerank", "state": "start"}
    if candidates:
        scores = models.rerank(req.question, [c["content"] for c in candidates])
        for candidate, score in zip(candidates, scores, strict=True):
            candidate["score"] = round(score, 4)
        candidates.sort(key=lambda c: c["score"], reverse=True)
    chunks = candidates[:req.top_k]
    log.info("retrieve %r: %d candidates -> %d chunks", req.question[:80], len(candidates), len(chunks))
    # the chunks go out now, so the UI shows the sources while the next agents are still answering
    yield {"step": "rerank", "state": "done", "detail": f"top {len(chunks)}", "chunks": chunks}

    result = {"question": req.question, "chunks": chunks}
    next_agents: list[dict] = []
    if send:
        endpoints = ", ".join(f"{port}{path}" for port, path in settings.next_agents)
        yield {"step": "send", "state": "start", "detail": endpoints}
        next_agents = _pass_to_next_agents(result)
        answered = sum("error" not in n for n in next_agents)
        yield {"step": "send", "state": "done", "detail": f"{answered} of {len(next_agents)} answered"}
    # No summary when passages are found: the verifier judges a step's summary if it has one, else its chunks,
    # so a summary like "found 2 passages" would hide the passages from it. Nothing found: failed + the reason
    # (the supervisor then tries the web).
    status = {"status": "ok"} if chunks else {
        "status": "failed", "summary": "No passage in the documents matches the question"}
    yield {"result": {**result, **status, "next_agents": next_agents}}


def _read_upload(file: UploadFile) -> tuple[str, bytes]:
    data = file.file.read()
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File is larger than {settings.max_upload_mb} MB")
    return file.filename or "upload", data


# ------------------------------------------------------------------------------------------------ routes
@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/card")
def card() -> dict:
    """What this agent does, for the supervisor's planning (utils.contracts.AgentCard)."""
    return {
        "name": "rag",
        "version": "1.0.0",
        "description": "Finds the passages of the user's uploaded documents that answer a question (hybrid dense + "
                       "sparse search in Qdrant, then reranked).",
        "when_to_use": "The question is about the user's own uploaded documents (contracts, reports, project rules, "
                       "policies, manuals).",
        "when_not_to_use": "Public or current information on the web (prices, news, weather); sending messages.",
        "examples": ["What is the retention money in the contract?", "Who issues the pegging sheet?"],
        "params_schema": {
            "type": "object",
            "properties": {"question": {"type": "string", "description": "the user's question"},
                           "top_k": {"type": "integer", "minimum": 1, "maximum": 50}},
            "required": ["question"],
        },
        "output_schema": {"type": "object", "properties": {"status": {}, "summary": {}, "question": {}, "chunks": {}}},
        "owner": "person-d",
    }


@app.post("/documents", status_code=201)
def upload_document(file: UploadFile) -> dict:
    return _run(_upload_steps(*_read_upload(file)))


@app.post("/documents/stream")
def upload_document_stream(file: UploadFile) -> StreamingResponse:
    """Same as POST /documents, as NDJSON step events (read, chunk, embed with progress, store) + the result."""
    return _stream(_upload_steps(*_read_upload(file)))


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


def retrieve_result(req: RetrieveRequest, forward: bool = True) -> dict:
    """The retrieve flow to its end (the JSON endpoint and the LangGraph graph)."""
    return _run(_retrieve_steps(req, forward))


@app.post("/retrieve")
def retrieve(req: RetrieveRequest) -> dict:
    """Returns {"question", "chunks": [{id, document_id, document_name, chunk_index, page, content, score}],
    "next_agents": [{endpoint, url, status, response} | {endpoint, url, error}, ...]}. Chunks are best
    first; score is the reranker's relevance (0..1). {question, chunks} is what the next agents receive.
    Also status (failed = no passage matched) and summary, the platform's step result."""
    return retrieve_result(req)


@app.post("/retrieve/stream")
def retrieve_stream(req: RetrieveRequest) -> StreamingResponse:
    """Same as POST /retrieve, as NDJSON step events (embed, search, rerank with the chunks, send) + the result."""
    return _stream(_retrieve_steps(req))


@app.post("/next-agents/retry")
def retry_next_agent(req: RetryRequest) -> dict:
    """POST {question, chunks} (as returned by /retrieve) again to one next agent; returns the same
    {endpoint, url, status, response} | {endpoint, url, error} as /retrieve. Only RAG_NEXT_AGENTS endpoints."""
    try:
        (endpoint,) = parse_endpoints(req.endpoint)
    except ValueError:  # not PORT/PATH, or not exactly one
        endpoint = None
    if endpoint not in settings.next_agents:
        raise HTTPException(status_code=404, detail=f"{req.endpoint!r} is not in RAG_NEXT_AGENTS")
    return _send(*endpoint, {"question": req.question, "chunks": req.chunks})
