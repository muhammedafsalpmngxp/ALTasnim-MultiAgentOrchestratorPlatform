# Backend: LangGraph multi-agent orchestrator

Every agent is **its own folder, its own LangGraph Agent Server deployment, its own port and Docker image**,
owned by one person/team. The whole backend has **one** `.env`, **one** `requirements.txt` and **one** `pyproject.toml`.

## Structure

```
backend/
├── .env / .env.example        ONE env file for all agents (loaded automatically; Docker passes it too)
├── requirements.txt           ONE requirements file: every dependency (all agents, dev tools, Docker)
├── pyproject.toml             ONE pyproject: packages utils + all agents as one project; pytest + ruff config
├── docker-compose.yml         all agents, each in its own container/port
├── .dockerignore
│
├── utils/                     [platform lead]  shared utilities: contracts every agent uses
│   ├── contracts.py           Plan, Step, SupervisorDecision, AgentTask, AgentResult, AgentCard, StepStatus
│   ├── context.py             RequestContext (LangGraph context_schema: tenant, user, roles)
│   ├── llm.py                 model factory (init_chat_model), rule-based fallback when no LLM set
│   ├── env.py                 loads backend/.env
│   ├── auth.py                dev/JWT user resolution for every auth.py
│   ├── events.py              custom stream events (get_stream_writer)
│   └── testing/               assert_agent_contract, run_agent_graph, build_stub_agent
│
├── orchestrator-agent/        [platform lead]  :8100   graph id: orchestrator
│   ├── Dockerfile · langgraph.json · README · CHANGELOG
│   ├── config/                agents.dev.yaml (agents + ports + transport), policies.yaml
│   ├── src/orchestrator_agent/
│   │   ├── graph.py           intake → supervisor → plan_guard → progress ⇄ run_agent / hitl_gate → respond
│   │   ├── state.py · settings.py · deps.py
│   │   ├── nodes/             intake, supervisor, clarify, plan_guard, progress, run_agent, hitl_gate, respond
│   │   ├── planning/          planner, rule_planner, llm_planner, validate, policies
│   │   ├── registry/          agent discovery (GET /card) + health
│   │   ├── clients/           local (in-process) / remote (langgraph_sdk) agent clients
│   │   ├── prompts/           supervisor.md
│   │   ├── auth.py            owner-scoped threads (langgraph_sdk.Auth)
│   │   └── api.py             /platform/agents, /platform/policies (http.app)
│   ├── tests/                 unit/ (planner, plan_guard)  graph/ (end-to-end flows)
│   └── evals/planning/        request → expected plan dataset
│
├── web_search_agent/          [Person A]  :8201   plan_queries → Send(search ×N) → summarize
├── communication-agent/       [Person B]  :8202   draft → approve (interrupt) → send
└── verifier-agent/            [Person C]  :8203   (check_evidence ‖ check_completeness) → verdict
    every agent folder:
      Dockerfile · langgraph.json · README.md · CHANGELOG.md     (no own requirements / pyproject)
      src/<package>/  graph.py  state.py  card.py  nodes/  auth.py  api.py  (+ tools/ prompts/ channels/)
      tests/          contract/  graph/
```

## Setup (conda)

Python 3.11 to 3.13 (LangGraph Agent Server does not support 3.14 yet). From `backend/`:

```powershell
conda activate <your-env>
pip install -r requirements.txt
copy .env.example .env
```

`pip install -r requirements.txt` installs every dependency **and** this project (`-e .`, from `pyproject.toml`),
so `utils` and all agent packages are importable everywhere.

## Test

```powershell
pytest
```

```powershell
ruff check .
```

## Run with Docker (step by step)

Prerequisite: Docker Desktop is running. All commands from `backend/`.

**1. Create the env file (once).** Every container reads it.

```powershell
copy .env.example .env
```

**2. Build the 4 images and start them** (orchestrator :8100, web-search :8201, communication :8202, verifier :8203):

```powershell
docker compose up --build -d
```

**3. Check all 4 are `healthy`.** The orchestrator starts after the 3 agents are healthy (about 20 s):

```powershell
docker compose ps
```

**4. Check the orchestrator discovered every agent:**

```powershell
curl http://localhost:8100/platform/agents
```

**5. Open the UI.** Start the frontend (`cd ..\frontend`, then `npm start`) and go to http://localhost:4200 → *Multi Agent Flow*.
Or use LangGraph Studio: `https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:8100`

**6. Follow one agent's logs:**

```powershell
docker compose logs -f communication-agent
```

**7. Stop everything:**

```powershell
docker compose down
```

Only your agent: `docker compose up -d --build <service>` (e.g. `verifier-agent`), or `node dev.mjs <agent>` from the
repo root, which also serves its UI. After changing code or `requirements.txt`, run step 2 again (`--build` rebuilds the images).
Add `--profile mail` in step 2 to also start Mailpit (set `EMAIL_CHANNEL=smtp` in `.env`; inbox at http://localhost:8025).

Notes:
- Each image contains the whole backend package but runs only its own agent.
- The images run `langgraph dev` (in-memory): runs are lost when a container restarts. For production, use the
  licensed Agent Server image (`langgraph build`) with Postgres and Redis.

## Run without Docker: each agent on its own port

Ports are the `<AGENT>_PORT` values in `backend/.env` (with Docker they are applied automatically; here pass the
same port to `--port`). One terminal per agent (conda env active), from the agent's folder:

```powershell
cd web_search_agent;    langgraph dev --port 8201 --no-browser
cd communication-agent; langgraph dev --port 8202 --no-browser
cd verifier-agent;      langgraph dev --port 8203 --no-browser
cd orchestrator-agent;  langgraph dev --port 8100 --no-browser
```

With `AGENT_TRANSPORT=remote` (in `.env`), the orchestrator calls the agents over HTTP.
Set `AGENT_TRANSPORT=local` to run all agent graphs inside the orchestrator process (no agent servers needed).

## Try it from Python

```python
import asyncio
from langgraph_sdk import get_client

async def main():
    c = get_client(url="http://127.0.0.1:8100")
    t = await c.threads.create()
    out = await c.runs.wait(t["thread_id"], "orchestrator",
                            input={"request": "check the price of iphone then share the mail to rijin@gmail.com"})
    print(out["plan"]["steps"])                               # plan JSON: which agents, in which order
    print(await c.threads.search(status="interrupted"))       # approvals inbox
    out = await c.runs.wait(t["thread_id"], "orchestrator", command={"resume": {"action": "approve"}})
    print(out["final"])

asyncio.run(main())
```

## Agent team rules

| Rule | Why |
|---|---|
| Graph input is exactly `{"task": AgentTask}`, output exactly `{"result": {...}}` | The orchestrator calls every agent the same way (`input_schema` / `output_schema`). |
| `result` has `status` (`ok`/`failed`/`rejected`) and `summary` | Replanning uses `status`; UI and emails show `summary`. |
| `card.py` with clear `when_to_use`, `when_not_to_use`, 2+ `examples`, `params_schema` | The supervisor plans only from cards. |
| `GET /card` in `api.py` | Discovery by the orchestrator. |
| `interrupt()` in its own node; side effects in a later node | Nodes re-run from the top on resume. |
| Never import another agent's package; use absolute imports | Agents only meet through the plan; `langgraph dev` loads `graph.py` by path. |

## Add an agent (e.g. `data`, port 8204)

1. Copy `verifier-agent/` to `data-agent/` and rename `src/verifier_agent` to `src/data_agent`
   (imports, graph id in `langgraph.json`, port in `Dockerfile`).
2. In `pyproject.toml`, add `"data-agent/src/data_agent"` to `packages` and `"data-agent/tests"` to `testpaths`.
   Put any new third-party package in `requirements.txt`.
3. Write `card.py` and `graph.py`. Make `tests/contract` pass.
4. Add the service to `docker-compose.yml`, the agent to `orchestrator-agent/config/agents.dev.yaml`,
   and the owner to `.github/CODEOWNERS`.

The supervisor plans with the new agent automatically, and the Multi Agent Flow UI shows it as a new node.
