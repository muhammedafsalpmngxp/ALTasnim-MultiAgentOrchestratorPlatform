# ALTasnim Multi-Agent Orchestrator Platform

A **supervisor (orchestrator) agent** reads each request, **plans which agents run and in which order**, runs the
plan (in parallel where possible), verifies the results, asks a human for approval when needed, and answers.

Everything is built on **[LangGraph](https://www.langchain.com/langgraph)**. Every agent is its own LangGraph Agent
Server deployment with its own folder, owner, port and Angular micro-frontend, so each team member builds one agent
independently.

```
 request ─► Supervisor LLM ─plan JSON─► plan_guard (check) ─► progress ──Send──► agents (parallel waves) ─┐
              ▲  (Routing)                                    ▲                                          │
              └────────── replan on failure ──────────────────┴── verifier (Reflection) ◄────────────────┘
                                                                  human approval (HITL) ─► action ─► answer
```

| Request | Plan created by the supervisor |
|---|---|
| What is the price of iPhone? | `web_search` → `verifier` |
| check the price of iphone then share the mail to rijin@gmail.com | `web_search` → `verifier` → `communication` (waits for approval) |
| Compare iPhone price in Oman and UAE and email it to rijin@gmail.com | `web_search` ‖ `web_search` → `verifier` → `communication` |
| check the iPhone price and email it | asks the user: "Who should I send it to?" |

## Repository structure

```
ALTasnim-MultiAgentOrchestratorPlatform/
├── backend/                        Python 3.12 · LangGraph · one Agent Server per agent
│   ├── .env.example                ONE env file for all agents (copy to .env)
│   ├── requirements.txt            ONE requirements file (all agents, dev tools, Docker)
│   ├── pyproject.toml              ONE pyproject (packages utils + all agents; pytest/ruff config)
│   ├── docker-compose.yml          all agents, each in its own container and port
│   ├── utils/                      shared utilities: contracts, LLM factory, env, auth, events, test kit
│   ├── superviser-agent/    :8100  supervisor (orchestrator) graph: every agent is one of its nodes
│   ├── web_search_agent/    :8201  plan_queries → parallel search → summarize
│   ├── communication-agent/ :8202  draft → human approval (interrupt) → send
│   ├── verifier-agent/      :8203  parallel checks → verdict
│   │   (each agent: Dockerfile · langgraph.json · README · CHANGELOG · src/ · tests/)
│   ├── Synthesizer-agent/   :8204  FastAPI: POST /synthesize (question + inputs) → the final answer (LLM)
│   └── Rag-agent/           :8000  FastAPI: ingest files → hybrid (dense + sparse) retrieval + rerank
│                                   (own docker-compose.yml with Qdrant; not a LangGraph deployment yet)
│
├── frontend/                       Angular 22 · Native Federation micro-frontends
│   ├── apps/shell/          :4200  host: layout, navigation, loads every micro-frontend
│   ├── apps/flow/           :4201  Multi Agent Flow: run a task, live flow diagram, approvals
│   ├── apps/runs/           :4202  run history + details
│   ├── apps/approvals/      :4203  human-in-the-loop inbox
│   ├── apps/admin/          :4204  agents & policies
│   ├── agents/*-ui/      :4301-4305  one UI per agent (owned by the agent's team)
│   └── libs/shared/                @altasnim/shared: LangGraph SDK client, flow diagram, shared UI
│
├── dev.mjs                         node dev.mjs <agent>: start only your agent (container + its UI)
└── .github/                        CODEOWNERS (one owner per agent: backend + UI folder), CI workflows
```

Details: [backend/README.md](backend/README.md) · [frontend/README.md](frontend/README.md)

## Work on your agent

Everyone works on the `pro` branch, each person in their own agent's folders (see [Team ownership](#team-ownership)).
Each agent is its own container and its own micro-frontend, so you start **only yours**.

Prerequisites: Docker Desktop (running), Node.js 20+ (tested with 24), Git. All commands run from the repo root.

**1. Get the code (once, then `git pull` before you start working)**

```powershell
git switch pro
git pull
```

**2. Start your agent: its container + its UI**

| Agent | Command | Container (API) | UI |
|---|---|---|---|
| Web search | `node dev.mjs web-search` | `web-search-agent` http://localhost:8201 | http://localhost:4301 |
| Communication | `node dev.mjs communication` | `communication-agent` http://localhost:8202 | http://localhost:4302 |
| Verifier | `node dev.mjs verifier` | `verifier-agent` http://localhost:8203 | http://localhost:4303 |
| Synthesizer | `node dev.mjs synthesizer` | `synthesizer-agent` http://localhost:8204 | http://localhost:4304 |
| Rag | `node dev.mjs rag` | Rag-agent `api` http://localhost:8000 + `qdrant` :6333 | http://localhost:4305 |
| Orchestrator (platform) | `node dev.mjs orchestrator` | `orchestrator-agent` http://localhost:8100 (+ the 3 agents it calls) | http://localhost:4200 (shell, flow, runs, approvals, admin) |

It builds and starts only that agent's container(s), then serves only its UI on its own port. The first run creates
`backend/.env` from `.env.example` (put your keys there) and runs `npm install`. `Ctrl+C` stops the UI; the container
keeps running. `node dev.mjs` lists the agents.

**3. While you work** (replace `rag` with your agent)

| Command | Does |
|---|---|
| `node dev.mjs rag --backend` | rebuilds + restarts only your container, after a backend code change (the UI keeps running) |
| `node dev.mjs rag --ui` | serves only your UI (the container is already running) |
| `node dev.mjs rag --shell` | also serves the shell: your UI inside the platform at http://localhost:4200 (other sections show "unavailable") |
| `node dev.mjs rag --stop` | stops your container(s) |

UI code changes reload in the browser by themselves. API ports are `<AGENT>_PORT` in `backend/.env`.

**Without the script:** the same two steps by hand, one terminal each.

| Agent | Container (from `backend/`) | UI (from `frontend/`) |
|---|---|---|
| Web search | `docker compose up -d --build web-search-agent` | `npm run start:web-search-ui` |
| Communication | `docker compose up -d --build communication-agent` | `npm run start:communication-ui` |
| Verifier | `docker compose up -d --build verifier-agent` | `npm run start:verifier-ui` |
| Synthesizer | `docker compose up -d --build synthesizer-agent` | `npm run start:synthesizer-ui` |
| Rag | `docker compose -f Rag-agent/docker-compose.yml --env-file .env up -d --build` | `npm run start:rag-ui` |
| Orchestrator | `docker compose up -d --build orchestrator-agent` | `npm run start:shell` (+ `start:flow`, `start:runs`, `start:approvals`, `start:admin`) |

Stop a container by hand: `docker compose stop <service>` (Rag: `docker compose -f Rag-agent/docker-compose.yml stop`).
Logs: `docker compose logs -f <service>` (Rag: `docker compose -f Rag-agent/docker-compose.yml logs -f`).

## Run everything

For the full platform on one machine (e.g. a demo). From the repo root:

**1. Backend: every agent in Docker**

```powershell
cd backend
copy .env.example .env
docker compose up -d --build
docker compose -f Rag-agent/docker-compose.yml --env-file .env up -d --build
docker compose ps
```

Skip `copy` if `backend/.env` already exists. Wait until all services show `healthy` (Rag-agent: `docker compose -f
Rag-agent/docker-compose.yml ps`; its models load in ~30 s).

**2. Frontend: every micro-frontend**, in a second terminal:

```powershell
cd frontend
npm install
npm start
```

**3. Open** http://localhost:4200, go to **Multi Agent Flow**, and try an example request.

**4. Stop:** `Ctrl+C` for the frontend, then from `backend/`:

```powershell
docker compose down
docker compose -f Rag-agent/docker-compose.yml down
```

`down` removes the containers but keeps the data volumes (Rag's documents and model cache). Add `-v` only to delete them.

## Local development (without Docker)

```powershell
conda activate <your-env>
cd backend
pip install -r requirements.txt
pytest
```

Run one agent: `cd backend/web_search_agent` then `langgraph dev --port 8201`. See [backend/README.md](backend/README.md).

## Team ownership

| Owner | Backend | Frontend |
|---|---|---|
| Platform lead | `backend/utils`, `backend/superviser-agent` | – |
| Frontend lead | – | `frontend/apps`, `frontend/libs` |
| Person A | `backend/web_search_agent` | `frontend/agents/web_search_ui` |
| Person B | `backend/communication-agent` | `frontend/agents/communication-ui` |
| Person C | `backend/verifier-agent` | `frontend/agents/verifier-ui` |
| Person D | `backend/Rag-agent` | `frontend/agents/rag-ui` |
| Person E | `backend/Synthesizer-agent` | `frontend/agents/synthesizer-ui` |

Only change your own folders. Shared files (`backend/.env.example`, `backend/requirements.txt`,
`backend/docker-compose.yml`, `frontend/proxy.conf.json`, the shell) belong to the platform and frontend leads.

Adding an agent: see the "Add an agent" sections in the backend and frontend READMEs. The supervisor and the flow
diagram pick up new agents automatically.

## Branches

| Branch | Purpose |
|---|---|
| `pro` | the team's branch: everyone works here, each on their own agent |
| `dev-1.0` | earlier development (merged into `pro`) |
| `main` | releases (by pull request) |

## Status

| Done | Next |
|---|---|
| Supervisor v1: its LLM (`SUPERVISOR_LLM_MODEL`) plans the flow from the agent cards and reviews on failures | Supervisor v2: guardrails (inserted verifier / approval steps, step and email rules) |
| Parallel execution, verification, replanning, human approval | Real web search provider (sample data today) |
| 4 agent deployments, Docker Compose, 31 backend tests | Real email/Teams sending (console / Mailpit today) |
| Angular micro-frontends with live flow diagram | JWT auth (`AUTH_MODE=jwt`), production Agent Server with Postgres/Redis |
