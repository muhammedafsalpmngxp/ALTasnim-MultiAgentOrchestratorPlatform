# L&T Files Assistant

On-premise AI assistant for L&T construction project documents.
Built on [RAGFlow](https://github.com/infiniflow/ragflow) — uses its full RAG pipeline (hybrid BM25+vector search, GraphRAG, reranking) unchanged.

```
backend/   ← FastAPI + RAGFlow pipeline (Python), Dockerfile.lt, docker-compose.prod.yml
frontend/  ← React + Vite + TypeScript + Tailwind
```

Commands below start from the project folder (the one that contains `backend/` and `frontend/`) unless a section says otherwise.

**Runs 100% locally at $0 cost, GPU-accelerated:** the LLM (Ollama, e.g. `qwen3.6:35b-a3b`),
embeddings (`BAAI/bge-m3`), reranker (`BAAI/bge-reranker-v2-m3`), and deepdoc OCR/layout/table
recognition all run on an NVIDIA GPU. No external API calls are required.

---

## Screenshots

### 1. Login Page
![Login Page](../frontend/docs/assets/login.png)

### 2. Projects Dashboard
![Projects Dashboard](../frontend/docs/assets/projects.png)

### 3. Chat Workspace
![Chat Workspace](../frontend/docs/assets/chat.png)

---

## Quick Start

### Recommended: full stack in one command (GPU-accelerated)

Runs everything — Elasticsearch, Redis, MySQL, MinIO, the backend API, 3 parallel document-parsing
workers, and the frontend — in Docker, with the GPU wired into the backend and workers.

**Prerequisites**
- Docker Desktop with the **NVIDIA GPU** enabled (WSL2 backend). Verify: `docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi`
- **[Ollama](https://ollama.com) running on the host** (it auto-starts in the background) with the model pulled:
  ```bash
  ollama pull qwen3.6:35b-a3b
  # optional: keep the model warm so chats don't cold-start
  setx OLLAMA_KEEP_ALIVE 1h    # Windows (restart Ollama after)
  ```
- `backend/.env` present (copy from `backend/.env.example`); set `LLM_PROVIDER=local` and `OLLAMA_MODEL=qwen3.6:35b-a3b`.

```bash
cd backend
docker compose -f docker-compose.prod.yml up -d --build   # first run / after code changes
docker compose -f docker-compose.prod.yml up -d           # subsequent restarts (no rebuild)
```
Then open **http://localhost** (frontend). The containers reach host-run Ollama via
`host.docker.internal:11434`. To stop (data persists in named volumes), from `backend/`: `docker compose -f docker-compose.prod.yml down`.

> Ollama runs **natively on the host, not in Docker** — this gives it direct, reliable GPU access.
> The Docker containers only make HTTP calls to it. See [GPU Acceleration](#gpu-acceleration) below.

---

## Manual (local dev, without the prod compose)

### 1. Start Infrastructure (Docker)

To run the required database, search engine, and task queue:
```bash
cd backend/docker
docker compose -f docker-compose-lt.yml up -d elasticsearch redis mysql
# Starts: Elasticsearch (port 9200) + Redis (port 6379) + MySQL (port 3306)
```

### 2. Backend Setup & Run

Navigate to the `backend` folder and follow these steps to configure and run the services:

```bash
cd backend

# Configure environment variables
# Copy .env.example to .env if you haven't already
cp .env.example .env
# Edit .env — set ADMIN_PASSWORD, LLM_PROVIDER, database credentials, and API keys

# Install Python dependencies
pip install -r requirements.txt
```

#### Run the API Server
* **On Windows (PowerShell)**:
  ```powershell
  $env:PYTHONPATH="."
  uvicorn api.main:app --reload --port 8000
  ```
* **On Linux / macOS**:
  ```bash
  PYTHONPATH=. uvicorn api.main:app --reload --port 8000
  ```

Interactive API documentation will be available at → http://localhost:8000/docs

#### Run the Task Executor (Required for document parsing/chunking)
* **On Windows (PowerShell)**:
  ```powershell
  $env:PYTHONPATH="."
  python -m rag.svr.task_executor
  ```
* **On Linux / macOS**:
  ```bash
  PYTHONPATH=. python -m rag.svr.task_executor
  ```

---

### 3. Frontend Setup & Run

To run the user interface:
```bash
cd frontend
npm install
npm run dev
```

* App will be running at → http://localhost:5173
* Login credentials (default): `admin` / `admin@123` (change in `backend/.env`)

---

## Configuration Settings

### LLM Provider
Set the `LLM_PROVIDER` in `backend/.env`:

| Value    | Model                                   | Required env var / prereq          |
|----------|-----------------------------------------|------------------------------------|
| `local`  | **Ollama on GPU** (e.g. `qwen3.6:35b-a3b`, set via `OLLAMA_MODEL`) | Ollama running on host; **free, no API cost** |
| `openai` | GPT-4o-mini (configurable)              | `OPENAI_API_KEY`                   |
| `groq`   | llama-3.3-70b (configurable)            | `GROQ_API_KEY`                     |
| `gemini` | Gemini 1.5 Flash                        | `GEMINI_API_KEY`                   |

`LLM_PROVIDER` is the default chat model — the intent router, the analysis agent, and the
standard RAG path all use it. For `local`, the chat model resolves to `OLLAMA_MODEL` served by
Ollama at `OLLAMA_BASE_URL`.

**Switching at runtime (admin):** the top bar shows a **Model** switch (e.g. `qwen3.6:35b-a3b` |
`gpt-4o-mini`). An admin's choice applies to every chat on its next message, with no restart, and
is saved in the database (`system_settings`, key `lt.llm_provider`), so it overrides `LLM_PROVIDER`
until changed back. A provider is only selectable once it is configured — for OpenAI, set
`OPENAI_API_KEY` (and optionally `OPENAI_MODEL`) in `backend/.env` and restart once. Other users
see which model is active. API: `GET /api/v1/models/providers`, `PUT /api/v1/models/active-provider`
with `{"provider": "openai" | "local" | null}` (`null` = back to the `.env` default).

### Database
Set the `DB_TYPE` in `backend/.env`:

| Value        | Use case              |
|--------------|-----------------------|
| `sqlite`     | Development (default) |
| `mysql`      | Production (used by the prod compose) |
| `postgresql` | Production            |

---

## GPU Acceleration

Every model runs on the NVIDIA GPU (verified on an RTX 6000 Ada, 48 GB VRAM):

| Component | Runs on | How |
|-----------|---------|-----|
| **LLM** (chat / router / agent) | GPU via **Ollama** (native host process) | `LLM_PROVIDER=local`, containers reach it at `host.docker.internal:11434` |
| **Embedding** (`bge-m3`) | GPU (in-process, fp16) | FlagEmbedding auto-detects CUDA |
| **Reranker** (`bge-reranker-v2-m3`) | GPU (in-process, fp16) | `RERANK_PROVIDER=bge`, `AGENT_RERANK=1` |
| **deepdoc** OCR / layout / table | GPU (onnxruntime CUDA) | CUDA-12 libs bundled in `Dockerfile.lt` |

Key points:
- **Ollama is NOT dockerized** — it runs as a native host process for direct GPU access. `docker-compose.prod.yml` grants the GPU to the `backend` and `task_executor` containers via an NVIDIA `deploy` reservation, and adds `host.docker.internal` so they can reach Ollama.
- **onnxruntime-gpu** needs CUDA 12 while torch ships CUDA 13; `Dockerfile.lt` installs the CUDA-12 runtime libs and sets `LD_LIBRARY_PATH` so deepdoc OCR uses the GPU (≈10× faster parsing).
- **Parallel parsing**: the prod compose runs **3 `task_executor` replicas** (each with a unique Redis consumer name via `$(hostname)`), so multiple document page-batches parse simultaneously (~3× throughput).
- **Device visibility**: `grep "\[DEVICE\]"` in the logs shows exactly which model is on GPU vs CPU.
- **Ollama keep-alive**: `OLLAMA_KEEP_ALIVE` in `backend/.env` (e.g. `1h`, `-1`, `30m`) keeps the model resident so chats don't cold-start; the app forwards it per request for the Ollama provider.

---

## Supported File Types

* **Standard Documents**: PDF, DOCX, XLSX, PPTX, TXT, MD, CSV, HTML, EPUB
* **Media & Audio**: PNG, JPG, JPEG, GIF, WAV, MP3, AAC, FLAC, MP4, AVI, MKV
* **CAD Files**: **DWG, DXF** (automatically converted to PDF via LibreOffice integration)
* **Emails**: EML, MSG

---

## Architecture

```
React frontend → FastAPI (backend/) ──→ RAGFlow pipeline (rag/, deepdoc/, agent/)
                       │
                 Elasticsearch   ← hybrid BM25 + dense vector search
                 Redis           ← document parse task queue
                 MySQL / SQLite  ← metadata (users, projects, documents, sessions)
```

---

## API Endpoints (40 total)

| Group        | Endpoints                                                      |
|--------------|----------------------------------------------------------------|
| Auth         | POST /login, POST /logout, GET /me, PUT /password             |
| Users        | CRUD /users                                                    |
| Projects     | CRUD /projects, GET /stats                                     |
| Documents    | Upload (DWG auto-convert), list, status, reparse, download    |
| Chat         | Sessions CRUD + SSE streaming messages                        |
| Search       | POST /search (hybrid), GET /chunks                            |
| Reports      | POST /generate, GET /session/{id} — Word/PDF export           |
| Models       | GET providers/active/embedding/rerank, POST /test             |
| System       | GET /health, /status, /info, /parsers, POST /reindex          |

Full interactive docs: http://localhost:8000/docs

---

## Backend reference

FastAPI backend using RAGFlow's RAG pipeline internally. Commands in this section run from `backend/`.

### Folder Structure

```
backend/
├── api/
│   ├── core/
│   │   ├── config.py      # Pydantic settings — all .env config
│   │   ├── auth.py        # JWT + bcrypt auth
│   │   └── deps.py        # FastAPI Depends (AuthUser, AdminUser)
│   ├── db/
│   │   ├── init_db.py     # Peewee DB init (SQLite/MySQL/PostgreSQL)
│   │   └── services/      # RAGFlow DB services (unchanged)
│   ├── routes/
│   │   ├── auth.py        # /auth/login|logout|me|password
│   │   ├── users.py       # /users CRUD
│   │   ├── projects.py    # /projects CRUD + /stats
│   │   ├── documents.py   # /documents upload (DWG→PDF) + status
│   │   ├── chat.py        # /chat/sessions + SSE streaming
│   │   ├── search.py      # /search hybrid + /chunks
│   │   ├── reports.py     # /reports Word/PDF export
│   │   ├── models.py      # /models LLM config + test
│   │   └── system.py      # /health + /status + /parsers
│   └── main.py            # FastAPI app entry point
├── rag/                   # RAGFlow — DO NOT MODIFY
├── deepdoc/               # RAGFlow DeepDoc — DO NOT MODIFY
├── agent/                 # RAGFlow agents — DO NOT MODIFY
├── common/                # RAGFlow common utils — DO NOT MODIFY
├── docker/
│   └── docker-compose-lt.yml   # ES + Redis
├── Dockerfile.lt          # Image for the API + task_executor
├── docker-compose.prod.yml # Full stack (see Quick Start)
├── .env                   # Local config (gitignored)
└── .env.example           # Config template
```

### Run (Development)

```bash
# 1. Infrastructure
cd docker && docker compose -f docker-compose-lt.yml up -d

# 2. Install deps
pip install uv
uv pip install --system -r requirements.txt

# 3. Start
cd ..   # back to backend/
PYTHONPATH=. uvicorn api.main:app --reload --port 8000
```

API docs: http://localhost:8000/docs

### Run (Production)

```bash
PYTHONPATH=. uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 4
```

Or with Docker (backend container only):
```bash
docker build -f Dockerfile.lt -t lt-assistant .
docker run -p 8000:8000 --env-file .env lt-assistant
```

#### Full stack in one command (recommended)

`docker-compose.prod.yml` (in `backend/`) starts the entire application — Elasticsearch, Redis,
MySQL, MinIO, backend API, task_executor worker, and the frontend — replacing the 4 separate
terminals used in local dev (vite, `docker-compose-lt.yml`, task_executor, uvicorn). This is
also what you run on a deployment server; the same file works unchanged.

```bash
docker compose -f docker-compose.prod.yml up -d --build   # first run / after code changes
docker compose -f docker-compose.prod.yml up -d           # subsequent restarts (no rebuild)
```

Then open **http://localhost** (frontend, served by nginx) — not port 5173, that's only the
Vite dev server used in local dev.

To stop (keeps all data — uploaded docs, DB, indexed chunks — in named volumes):
```bash
docker compose -f docker-compose.prod.yml down
```

View logs:
```bash
docker logs -f lt_backend
# task_executor runs as 3 parallel replicas (task_executor-1/2/3) — follow all via compose:
docker compose -f docker-compose.prod.yml logs -f task_executor
docker compose -f docker-compose.prod.yml logs -f   # all services, interleaved
```

> **GPU / local LLM:** the prod compose grants the NVIDIA GPU to `backend` + `task_executor`
> and reaches host-run **Ollama** at `host.docker.internal:11434`. The chat LLM is chosen by
> `LLM_PROVIDER=local` (`OLLAMA_MODEL`); embeddings, reranker, and deepdoc OCR run on the GPU.
> `grep "\[DEVICE\]"` in the logs confirms GPU vs CPU. See [GPU Acceleration](#gpu-acceleration) above.

Deploying to a real server uses this same file — just populate `backend/.env` with production
secrets/API keys and put a reverse proxy (or Cloudflare Tunnel) in front for HTTPS/a real domain.

### Environment Variables

See [.env.example](.env.example) for all available settings.

Key variables:
- `LLM_PROVIDER` — `local` (Ollama, GPU) | `openai` | `groq` | `gemini` — single source of truth for the chat model
- `OLLAMA_MODEL` / `OLLAMA_BASE_URL` — model name (e.g. `qwen3.6:35b-a3b`) and Ollama endpoint (host)
- `OLLAMA_KEEP_ALIVE` — keep the model warm (e.g. `1h`, `-1`, `30m`) so chats don't cold-start
- `EMBEDDING_PROVIDER` / `RERANK_PROVIDER` — `bge` = local `BAAI/bge-*` on GPU (in-process)
- `AGENT_RERANK` — `1` to enable reranking inside the analysis agent (fast on GPU)
- `DB_TYPE` (a.k.a. `LT_DB_TYPE`) — `sqlite` | `mysql` | `postgresql`
- `ADMIN_USERNAME` / `ADMIN_PASSWORD` — default admin credentials
- `JWT_SECRET_KEY` — **change this in production**
- `ES_HOST` — Elasticsearch URL
- `REDIS_URL` — Redis URL

### Task Queue (Document Parsing)

Documents are parsed asynchronously via Redis Streams:
1. Upload endpoint saves file + DB record, pushes to `te.0.common` stream
2. RAGFlow's `task_executor.py` worker consumes from the stream
3. Parser runs (PDF layout, OCR, chunking, embedding, ES indexing)
4. Document status updates to `done` or `failed`

Run the worker separately (local dev — single worker):
```bash
PYTHONPATH=. python -m rag.svr.task_executor
```

In production (`docker-compose.prod.yml`) the worker runs as **3 replicas** so several document
page-batches parse in parallel. Each replica gets a unique Redis consumer name (`-i $(hostname)`)
and its own GPU-loaded models, and they share one consumer group so tasks are distributed, not
duplicated. Tune the count via `deploy.replicas` on the `task_executor` service.
