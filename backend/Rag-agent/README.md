# Rag-agent

Upload documents, then retrieve the most relevant chunks for a question with **hybrid search**
(BM25 keyword + dense vector) and **reranking**. No LLM call and no OCR: the question and the
reranked chunks are returned for the next agent to answer from.

```
UPLOAD    file ─► text (PDF text layer, DOCX, TXT/MD/CSV) ─► ~300-word chunks ─► bge-m3 vectors ─► Elasticsearch

RETRIEVE  question ─► bge-m3 vector ─┬─► BM25 search  (top 20) ─┐
                                     └─► dense kNN    (top 20) ─┴─► reciprocal rank fusion (top 20)
                                                                      ─► bge-reranker-v2-m3 ─► top_k chunks
```

## Run (Docker)

Needs Docker Desktop (with the NVIDIA GPU enabled, or delete the `deploy:` block in
`docker-compose.yml` to run on CPU).

```bash
cd backend/Rag-agent
docker compose up -d --build
```

Open http://localhost:8000/docs. The first upload/question downloads the models (~4.5 GB, cached in
the `models` volume), so it is slow once. Logs: `docker compose logs -f api`. Stop: `docker compose down`
(add `-v` to delete the index and the model cache).

## API

| Method | Path | Does |
|---|---|---|
| POST | `/documents` | Upload a file (multipart `file`) → `{document_id, document_name, chunks}` |
| GET | `/documents` | Uploaded documents with chunk counts |
| GET | `/documents/{document_id}/chunks` | A document's chunks, in order |
| DELETE | `/documents/{document_id}` | Remove a document and its chunks |
| POST | `/retrieve` | `{"question": "...", "top_k": 5}` → `{question, chunks}` |
| GET | `/health` | Liveness |

`/retrieve` returns chunks best first:

```json
{
  "question": "what is the retention money?",
  "chunks": [
    {"id": "…_3", "document_id": "…", "document_name": "contract.pdf", "chunk_index": 3,
     "page": 12, "content": "…", "score": 0.93}
  ]
}
```

`score` is the reranker's relevance (0..1). `page` is set for PDFs only.

There is no authentication: keep port 8000 on localhost or the internal network.

## Configuration

Environment variables, all optional (see `.env.example`; copy it to `.env` to change them):
`ES_URL`, `ES_INDEX`, `EMBEDDING_MODEL`, `RERANK_MODEL`, `CHUNK_WORDS`, `CHUNK_OVERLAP_WORDS`,
`CANDIDATES` (hits per search leg, and sent to the reranker), `TOP_K` (default for `/retrieve`),
`MAX_UPLOAD_MB`.

## Code

| File | |
|---|---|
| `rag_agent/main.py` | FastAPI routes: upload flow and retrieve flow |
| `rag_agent/parsing.py` | File → text (no OCR) |
| `rag_agent/chunking.py` | Text → chunks, keeping line breaks, with overlap |
| `rag_agent/models.py` | bge-m3 embeddings and bge reranker (GPU fp16 when available) |
| `rag_agent/store.py` | Elasticsearch index, BM25 + kNN search, rank fusion |

## Test

```bash
cd backend/Rag-agent
pip install -r requirements.txt
pytest
```

The tests use fake models and a fake Elasticsearch, so they need neither.
