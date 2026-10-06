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
| What is the price of iPhone 16 in India? | `web_search` → `synthesizer` → check (`verifier`, added by the platform) |
| check the price of iphone then share the mail to rijin@gmail.com | `web_search` → check → `communication` (waits for approval) |
| Compare iPhone price in Oman and UAE and email it to rijin@gmail.com | `web_search` ‖ `web_search` → check → `communication` |

The check only asks: does the answer match the question (every part answered, same topic)? It reads no sources and
searches nothing. A failed check sends the supervisor back to write the answer again, up to `SUPERVISOR_MAX_REPLANS`
times; then it answers honestly.
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
│   ├── superviser_agent/    :8100  supervisor (orchestrator) graph: every agent is one of its nodes
│   ├── web_search_agent/    :8201  plan_queries → parallel search → summarize
│   ├── communication_agent/ :8202  draft → human approval (interrupt) → send
│   ├── verifier_agent/      :8203  does the answer match the question → verdict
│   │   (each agent: Dockerfile · langgraph.json · README · CHANGELOG · src/ · tests/)
│   ├── synthesizer_agent/   :8204  FastAPI: POST /synthesize (question + inputs) → the final answer (LLM)
│   └── rag_agent/           :8000  FastAPI: ingest files → hybrid (dense + sparse) retrieval + rerank
│                                   (own docker-compose.yml with Qdrant; LangGraph graph "rag")
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

**2. Start your agent: its container + its UI** (one terminal each; the first time, copy `backend/.env.example` to
`backend/.env` and put your keys there, and run `npm install` in `frontend/`)

| Agent | Container (from `backend/`) | UI (from `frontend/`) |
|---|---|---|
| Web search | `docker compose up -d --build web-search-agent` | `npm run start:web-search-ui` |
| Communication | `docker compose up -d --build communication-agent` | `npm run start:communication-ui` |
| Verifier | `docker compose up -d --build verifier-agent` | `npm run start:verifier-ui` |
| Synthesizer | `docker compose up -d --build synthesizer-agent` | `npm run start:synthesizer-ui` |
| Rag | `docker compose -f rag_agent/docker-compose.yml --env-file .env up -d --build` | `npm run start:rag-ui` |
| Orchestrator | `docker compose up -d --build orchestrator-agent` | `npm run start:shell` (+ `start:flow`, `start:runs`, `start:approvals`, `start:admin`) |

API ports: web search 8201, communication 8202, verifier 8203, synthesizer 8204, rag 8000 (+ Qdrant 6333), orchestrator
8100 (`<AGENT>_PORT` in `backend/.env`). UIs: 4301-4305, the platform shell 4200. After a backend code change run the
same `docker compose up -d --build <service>` again; UI code changes reload in the browser by themselves.

Stop a container by hand: `docker compose stop <service>` (Rag: `docker compose -f rag_agent/docker-compose.yml stop`).
Logs: `docker compose logs -f <service>` (Rag: `docker compose -f rag_agent/docker-compose.yml logs -f`).

## Run everything

For the full platform on one machine (e.g. a demo). From the repo root:

**1. Backend: every agent in Docker**

```powershell
cd backend
copy .env.example .env
docker compose up -d --build
docker compose -f rag_agent/docker-compose.yml --env-file .env up -d --build
docker compose ps
```

Skip `copy` if `backend/.env` already exists. Wait until all services show `healthy` (rag_agent: `docker compose -f
rag_agent/docker-compose.yml ps`; its models load in ~30 s).

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
docker compose -f rag_agent/docker-compose.yml down
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
| Platform lead | `backend/utils`, `backend/superviser_agent` | – |
| Frontend lead | – | `frontend/apps`, `frontend/libs` |
| Person A | `backend/web_search_agent` | `frontend/agents/web_search_ui` |
| Person B | `backend/communication_agent` | `frontend/agents/communication-ui` |
| Person C | `backend/verifier_agent` | `frontend/agents/verifier-ui` |
| Person D | `backend/rag_agent` | `frontend/agents/rag-ui` |
| Person E | `backend/synthesizer_agent` | `frontend/agents/synthesizer-ui` |

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
| Supervisor v1: its LLM (`SUPERVISOR_LLM_MODEL`) plans the flow from the agent cards and reviews on failures | Supervisor v2: step and email rules |
| Parallel execution, a platform check that every answer matches the question, targeted replanning, human approval | Synthesizer: a stronger model (it sometimes adds facts from memory) |
| 6 LangGraph deployments (live web search, RAG, verifier, synthesizer, email via SMTP), 300 backend tests | Teams channel; a company mailbox (SPF/DKIM) instead of a personal Gmail |
| Angular micro-frontends with live flow diagram | JWT auth (`AUTH_MODE=jwt`), production Agent Server with Postgres/Redis |
