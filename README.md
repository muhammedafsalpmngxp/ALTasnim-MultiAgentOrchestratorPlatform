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
│   ├── web-search-agent/    :8201  plan_queries → parallel search → summarize
│   ├── communication-agent/ :8202  draft → human approval (interrupt) → send
│   └── verifier-agent/      :8203  parallel checks → verdict
│       (each agent: Dockerfile · langgraph.json · README · CHANGELOG · src/ · tests/)
│
├── frontend/                       Angular 22 · Native Federation micro-frontends
│   ├── apps/shell/          :4200  host: layout, navigation, loads every micro-frontend
│   ├── apps/flow/           :4201  Multi Agent Flow: run a task, live flow diagram, approvals
│   ├── apps/runs/           :4202  run history + details
│   ├── apps/approvals/      :4203  human-in-the-loop inbox
│   ├── apps/admin/          :4204  agents & policies
│   ├── agents/*-ui/      :4301-4303  one UI per agent (owned by the agent's team)
│   └── libs/shared/                @altasnim/shared: LangGraph SDK client, flow diagram, shared UI
│
└── .github/                        CODEOWNERS (one owner per agent: backend + UI folder), CI workflows
```

Details: [backend/README.md](backend/README.md) · [frontend/README.md](frontend/README.md)

## Quick start

Prerequisites: Docker Desktop, Node.js 20+ (tested with 24). For local Python development: Python 3.11–3.13 (conda env).

**1. Backend (4 agent deployments in Docker)**

```powershell
cd backend
copy .env.example .env
docker compose up --build -d
docker compose ps
```

Wait until all 4 services show `healthy`.

**2. Frontend (8 micro-frontends)**, in a second terminal:

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

Run one agent: `cd backend/web-search-agent` then `langgraph dev --port 8201`. See [backend/README.md](backend/README.md).

## Team ownership

| Owner | Backend | Frontend |
|---|---|---|
| Platform lead | `backend/utils`, `backend/orchestrator-agent` | – |
| Frontend lead | – | `frontend/apps`, `frontend/libs` |
| Person A | `backend/web-search-agent` | `frontend/agents/web-search-ui` |
| Person B | `backend/communication-agent` | `frontend/agents/communication-ui` |
| Person C | `backend/verifier-agent` | `frontend/agents/verifier-ui` |

Adding an agent: see the "Add an agent" sections in the backend and frontend READMEs. The supervisor and the flow
diagram pick up new agents automatically.

## Branches

| Branch | Purpose |
|---|---|
| `dev-1.0` | active development (this code) |
| `main` | releases (merge from `dev-1.0` by pull request) |

## Status

| Done | Next |
|---|---|
| Supervisor planning (rule-based offline planner; LLM planner ready) | Connect an LLM provider (`LLM_MODEL_*` in `backend/.env`) |
| Parallel execution, verification, replanning, human approval | Real web search provider (sample data today) |
| 4 agent deployments, Docker Compose, 31 backend tests | Real email/Teams sending (console / Mailpit today) |
| Angular micro-frontends with live flow diagram | JWT auth (`AUTH_MODE=jwt`), production Agent Server with Postgres/Redis |
