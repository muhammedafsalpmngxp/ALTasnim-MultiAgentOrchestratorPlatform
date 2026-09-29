# ALTasnim Multi-Agent Orchestrator Platform

A **supervisor (orchestrator) agent** reads each request, **plans which agents run and in which order**, runs the
plan (in parallel where possible), verifies the results, asks a human for approval when needed, and answers.

Everything is built on **[LangGraph](https://www.langchain.com/langgraph)**. Every agent is its own LangGraph Agent
Server deployment with its own folder, owner, port and Angular micro-frontend, so each team member builds one agent
independently.

```
 request ─► Supervisor ──plan JSON──► plan_guard (policy) ─► progress ──Send──► agents (parallel waves) ─┐
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
│   ├── orchestrator-agent/  :8100  supervisor, plan_guard, progress, run_agent, hitl_gate, respond
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
Each agent is its own container and its own micro-frontend, so you start **only yours**. From the repo root:

```powershell
git switch pro
git pull
node dev.mjs rag
```

This builds and starts only that agent's container(s), then serves only its UI on its own port. `Ctrl+C` stops the UI,
and the container keeps running. The first run creates `backend/.env` from `.env.example` and runs `npm install`.

| Agent | Command | Container (API) | UI |
|---|---|---|---|
| Web search | `node dev.mjs web-search` | `web-search-agent` :8201 | `web-search-ui` http://localhost:4301 |
| Communication | `node dev.mjs communication` | `communication-agent` :8202 | `communication-ui` http://localhost:4302 |
| Verifier | `node dev.mjs verifier` | `verifier-agent` :8203 | `verifier-ui` http://localhost:4303 |
| Synthesizer | `node dev.mjs synthesizer` | `synthesizer-agent` :8204 | `synthesizer-ui` http://localhost:4304 |
| Rag | `node dev.mjs rag` | Rag-agent `api` :8000 + `qdrant` :6333 | `rag-ui` http://localhost:4305 |
| Orchestrator (platform) | `node dev.mjs orchestrator` | `orchestrator-agent` :8100 (+ the 3 agents it calls) | shell, flow, runs, approvals, admin http://localhost:4200 |

| Add | Does |
|---|---|
| `--shell` | also serves the shell, so you see your UI inside the platform at http://localhost:4200 (other sections show "unavailable") |
| `--backend` | only rebuilds + restarts your container (after a backend code change; the UI keeps running) |
| `--ui` | only serves your UI (the container is already running) |
| `--stop` | stops your container(s) |

`node dev.mjs` lists the agents. API ports are `<AGENT>_PORT` in `backend/.env`.

## Run everything

Prerequisites: Docker Desktop, Node.js 20+ (tested with 24). For local Python development: Python 3.11–3.13 (conda env).

**1. Backend (every agent in Docker)**

```powershell
cd backend
copy .env.example .env
docker compose up --build -d
docker compose ps
```

Wait until all services show `healthy`. Rag-agent has its own compose file (with Qdrant):
`docker compose -f Rag-agent/docker-compose.yml --env-file .env up -d --build`.

**2. Frontend (every micro-frontend)**, in a second terminal:

```powershell
cd frontend
npm install
npm start
```

**3. Open** http://localhost:4200, go to **Multi Agent Flow**, and try an example request.

Stop the backend with `docker compose down`, and the frontend with `Ctrl+C`.

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
| Platform lead | `backend/utils`, `backend/orchestrator-agent` | – |
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
| Supervisor planning (rule-based offline planner; LLM planner ready) | Connect an LLM provider (`LLM_MODEL_*` in `backend/.env`) |
| Parallel execution, verification, replanning, human approval | Real web search provider (sample data today) |
| 4 agent deployments, Docker Compose, 31 backend tests | Real email/Teams sending (console / Mailpit today) |
| Angular micro-frontends with live flow diagram | JWT auth (`AUTH_MODE=jwt`), production Agent Server with Postgres/Redis |
