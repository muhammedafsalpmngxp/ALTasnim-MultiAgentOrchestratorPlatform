# Rag-agent

Upload documents, then retrieve the most relevant chunks for a question with **hybrid search**
(sparse keyword vectors + dense vectors, in [Qdrant](https://qdrant.tech)) and **reranking**. No LLM
call and no OCR: the question and the reranked chunks are passed to the next agents, which answer.

```
UPLOAD    file ─► text (PDF text layer, DOCX, TXT/MD/CSV) ─► ~300-word chunks
               ─► bge-m3 (one pass: dense + sparse vector per chunk) ─► Qdrant

RETRIEVE  question ─► bge-m3 dense + sparse ─┬─► sparse search (keywords, top 20) ─┐  RRF fusion
                                             └─► dense search  (meaning,  top 20) ─┴─ in Qdrant (top 20)
                                                    ─► bge-reranker-v2-m3 ─► top_k chunks
                                                    ─► POST {question, chunks} to each RAG_NEXT_AGENTS endpoint
```

The sparse vector is bge-m3's lexical weights (a learned per-token keyword weight), so exact terms
such as clause numbers or material names match even when the dense vector alone would miss them.

## Run (Docker)

Needs Docker Desktop (with the NVIDIA GPU enabled, or delete the `deploy:` block in
`docker-compose.yml` to run on CPU).

```bash
cd backend/Rag-agent
docker compose --env-file ../.env up -d --build
```

`--env-file ../.env` makes compose read the shared `backend/.env` (e.g. `RAG_PORT`) for the port mapping.

- API + Swagger UI: http://localhost:8000/docs (port = `RAG_PORT` in `backend/.env`)
- Qdrant dashboard (collection, points, vectors): http://localhost:6333/dashboard
- UI: the **RAG** page in the platform frontend (`frontend/agents/rag-ui`, :4305): ingest files, and
  a chat window that shows the retrieved chunks and each next agent's reply

The models load when the API starts (~30 s; the very first start also downloads them, ~4.5 GB, cached
in the `models` volume). Logs: `docker compose logs -f api`. Stop: `docker compose down` (add `-v` to
delete the stored chunks and the model cache).

## API

| Method | Path | Does |
|---|---|---|
| POST | `/documents` | Upload a file (multipart `file`) → `{document_id, document_name, chunks}` |
| GET | `/documents` | Uploaded documents with chunk counts |
| GET | `/documents/{document_id}/chunks` | A document's chunks, in order |
| DELETE | `/documents/{document_id}` | Remove a document and its chunks |
| POST | `/retrieve` | `{"question": "...", "top_k": 5}` → `{question, chunks, next_agents}` |
| POST | `/documents/stream`, `/retrieve/stream` | Same as `/documents` and `/retrieve`, but report every step live as NDJSON lines: `{plan}`, then `{step, state: start / progress / done, detail, progress}`, then `{result}` (or a last `{error}`). The UI's animated progress uses them; the ranked chunks arrive before the next agents answer |
| POST | `/next-agents/retry` | `{"endpoint": "8204/synthesize", "question", "chunks"}` → sends them again to that next agent (the UI's **Retry** button); one `next_agents` entry |
| GET | `/health` | Liveness |

`/retrieve` returns chunks best first, and what each next agent replied:

```json
{
  "question": "what is the retention money?",
  "chunks": [
    {"id": "…", "document_id": "…", "document_name": "contract.pdf", "chunk_index": 3,
     "page": 12, "content": "…", "score": 0.93}
  ],
  "next_agents": [
    {"endpoint": "8203/synthesize", "url": "http://192.168.1.33:8203/synthesize", "status": 200,
     "response": {"status": "ok", "answer": "…"}}
  ]
}
```

`score` is the reranker's relevance (0..1). `page` is set for PDFs only. A next agent that fails shows
`{"endpoint", "url", "error"}` instead; the chunks are always returned.

## Next agents (automatic, no IPs)

`RAG_NEXT_AGENTS` lists `PORT/PATH` endpoints, comma-separated (`8203/synthesize, 8210/answer`). Each
`/retrieve` POSTs `{"question": ..., "chunks": [...]}` to all of them in parallel. For each endpoint,
Rag-agent scans `RAG_NEXT_AGENT_SUBNET` (e.g. `192.168.1.0/24`) for machines with the port open and uses
the first whose `/openapi.json` lists the path. Other services on the same port (such as a teammate's
verifier agent on 8203) are skipped, and no document data is sent while searching. The machine is
remembered; if it stops answering it is searched again once. Inside Docker the container can't see the
Wi-Fi network by itself, so the subnet must be set; outside Docker an empty subnet means "this machine's
own /24".

There is no authentication: keep ports 8000 and 6333 on localhost or the internal network.

## Configuration

The `RAG_*` keys of the one shared `backend/.env` (template and descriptions: `backend/.env.example`, section
`Rag-agent`), all optional: `RAG_QDRANT_URL`, `RAG_QDRANT_COLLECTION`, `RAG_EMBEDDING_MODEL`, `RAG_RERANK_MODEL`,
`RAG_CHUNK_WORDS`, `RAG_CHUNK_OVERLAP_WORDS`, `RAG_CANDIDATES` (hits per search, and sent to the reranker),
`RAG_TOP_K` (default for `/retrieve`), `RAG_MAX_UPLOAD_MB`, `RAG_NEXT_AGENTS`, `RAG_NEXT_AGENT_SUBNET`,
`RAG_NEXT_AGENT_TIMEOUT`. `docker-compose.yml` passes `backend/.env` in; after editing, restart with
`docker compose --env-file ../.env up -d`.

## Code

| File | |
|---|---|
| `rag_agent/main.py` | FastAPI routes: upload flow and retrieve flow |
| `rag_agent/parsing.py` | File → text (no OCR) |
| `rag_agent/chunking.py` | Text → chunks, keeping line breaks, with overlap |
| `rag_agent/models.py` | bge-m3 dense + sparse embeddings, bge reranker (GPU fp16 when available) |
| `rag_agent/store.py` | Qdrant collection, hybrid query (dense + sparse, RRF), documents |
| `rag_agent/discovery.py` | Finds each next agent on the LAN by port + path (no IPs) |

## Test

```bash
cd backend/Rag-agent
pip install -r requirements.txt
pytest
```

The tests run the real store against Qdrant's in-memory mode and use stand-ins for the models, so
they need neither a Qdrant server nor a model download.
