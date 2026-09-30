# synthesizer-agent

**Owner:** Person D (team-synthesizer) · **Port:** `SYNTHESIZER_PORT` in `backend/.env` (8203; 8204 in Docker) · a **LangGraph** deployment (graph `synthesizer`) with FastAPI routes

A simple answering agent: it takes the outputs of earlier agents (for example the verifier), puts them in
the prompt with the user's question, and returns the LLM's answer.

| File | What it is |
|---|---|
| `src/synthesizer_agent/agent.py` | The whole agent: `answer(question, inputs)` builds the prompt, calls the LLM |
| `src/synthesizer_agent/prompts/system.md` | How to work and format the answer (today's date is filled in) |
| `src/synthesizer_agent/prompts/user.md` | The question, the numbered sources and the data |
| `run.py` | Starts the agent with `SYNTHESIZER_HOST` / `SYNTHESIZER_PORT` from `backend/.env` |
| `src/synthesizer_agent/api.py` | The API: `GET /ok`, `GET /card`, `POST /synthesize` |
| `src/synthesizer_agent/card.py` | Description of the agent, served at `/card` |
| `src/synthesizer_agent/runs.py` | Remembers recent requests for the UI (`GET /runs`) |
| `src/synthesizer_agent/graph.py` | The LangGraph graph `synthesizer` the supervisor runs: `{"task"}` in, `{"result"}` out |
| `src/synthesizer_agent/server.py` | The routes under LangGraph: api.py without the catch-alls (they would hide its API) |
| `langgraph.json` | Serves the graph + the routes: `langgraph dev` (the Docker image does this) |
| UI | Angular micro-frontend in the team frontend: `frontend/agents/synthesizer-ui` (port 4304) |

## API

**Receives anything:** `POST` / `PUT` / `PATCH` on **any path** (`/synthesize`, `/verify`, `/`, ...), with any body:
a JSON object, a list, or plain text.

```json
{"question": "What is the price of iPhone 16 in Oman?",
 "chunks": ["Apple Oman: iPhone 16 from OMR 329", "Lulu Oman: iPhone 16 128GB OMR 319"]}
```

- The question is taken from `question`, `query`, `q`, `prompt`, `user_question`, `request`, `message` or
  `objective` (also inside `task` / `params` / `input` / `data`). Without one, the LLM works out what is asked.
- Everything else is the data the answer is written from. Source URLs (`sources` lists, `url` fields) are
  collected from anywhere in it.
- `GET` on an unknown path answers `{"ok": true, "agent": "synthesizer"}` instead of 404.

Reply: `{"status": "ok", "summary": "<answer>", "answer": "<answer>", "sources": [...]}`.
`status` is `failed` when the request has no data; `502` if the LLM call fails.

For the UI: `GET /runs` (recent requests, newest first, with the path they came in on), `GET /runs/{id}` (with
the prompt sent to the LLM), `DELETE /runs`. Kept in memory only (`SYNTHESIZER_MAX_RUNS`, default 50).

## Settings (in `backend/.env`)

```
SYNTHESIZER_HOST=0.0.0.0   # 0.0.0.0 = reachable from other computers
SYNTHESIZER_PORT=8203      # the port other agents send to; the UI reads it too (npm start)
SYNTHESIZER_RELOAD=true    # restart automatically on code changes
```

## LLM (in `backend/.env`)

```
SYNTHESIZER_OPENAI_BASE_URL=https://api.openai.com/v1   # or Azure OpenAI, a proxy, Ollama http://localhost:11434/v1
SYNTHESIZER_OPENAI_API_KEY=sk-...                        # needed for OpenAI; local servers need none
SYNTHESIZER_OPENAI_MODEL=gpt-4o-mini
```

Without a model (or OpenAI without a key), the answer is the inputs' summaries. Restart after changing `.env`.

## Run

```powershell
cd backend\Synthesizer-agent
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

Docs: http://localhost:8203/docs · Tests: `pytest tests`

UI: in the team `frontend/` folder, `npm.cmd start` (all screens, open http://localhost:4200 → Synthesizer) or `npm.cmd run start:synthesizer-ui` (only this UI, http://localhost:4304)

`SYNTHESIZER_CORS_ORIGINS` in `backend/.env` lists the browser apps allowed to call the API.

## Docker

Self-contained image (only this folder; runs as a non-root user; test tools are not installed). From
`backend/Synthesizer-agent`:

```powershell
docker build -t altasnim/synthesizer-agent .
docker run --rm -p 8203:8203 --env-file ../.env -e SYNTHESIZER_RELOAD=false altasnim/synthesizer-agent
```

Settings and the OpenAI key come from `backend/.env` at run time; they are never copied into the image
(`.dockerignore`). With the team setup: `docker compose up --build synthesizer-agent` (container port 8204).

## Supervisor

The synthesizer is a node of the supervisor graph (`superviser-agent/config/agents.dev.yaml`): the last step of
every question. The supervisor runs the graph `synthesizer` on `SYNTHESIZER_PORT` with the question
(`task.params.question`) and the earlier steps' outputs (`task.inputs`: the passages or web results, and the
verifier's verdict), and replies with its answer. Those calls are listed in `GET /runs` too.

The image runs `langgraph dev` (graph + routes). `python run.py` still runs the plain FastAPI app alone, with the
catch-all routes (POST on any path).
