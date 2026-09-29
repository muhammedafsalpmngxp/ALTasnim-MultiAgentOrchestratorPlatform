# Changelog

## 0.7.1 - 2026-09-29

- Self-contained Dockerfile (build from this folder, runtime packages only, non-root user, port from `SYNTHESIZER_PORT`) and `.dockerignore`; docker-compose builds from `./Synthesizer-agent`.
- The UI moved to the team frontend: `frontend/agents/synthesizer-ui`. The old copy in `Synthesizer-agent/frontend/` was removed.

## 0.7.0 - 2026-09-28

- Port from `backend/.env`: `SYNTHESIZER_HOST`, `SYNTHESIZER_PORT`, `SYNTHESIZER_RELOAD`; start with `python run.py`. The UI reads the same port (npm prestart writes public/synthesizer-config.json).
- Better prompt: system + user messages, today's date, numbered sources to cite, answer-first format, same language as the question.
- Professional UI: app bar, stats, search, answer first with copy, collapsible behind-the-scenes, toasts.

## 0.6.0 - 2026-09-28

- Receives anything: any path and method (POST/PUT/PATCH), JSON or text. Finds the question in common fields, or the LLM works it out. Unknown GETs answer ok instead of 404.
- Prompt asks the LLM to work out the question and the relevant data before answering.
- The UI shows the path and method each request came in on.

## 0.5.0 - 2026-09-28

- Micro-frontend `frontend/` (`synthesizer-ui`, Angular Native Federation remote, port 4304).
- `GET /runs`, `GET /runs/{id}`, `DELETE /runs` (recent requests for the UI), CORS (`SYNTHESIZER_CORS_ORIGINS`), `502` when the LLM fails.

## 0.4.0 - 2026-09-28

- Removed LangGraph: plain FastAPI app with `POST /synthesize` (`question` + `inputs`), `GET /ok`, `GET /card`.
- Self-contained: own `requirements.txt`, reads `backend/.env` itself, runs with `uvicorn`.
- Disabled in the orchestrator registry (it only calls LangGraph agents).

## 0.3.0 - 2026-09-28

- Own OpenAI LLM settings: `SYNTHESIZER_OPENAI_BASE_URL`, `SYNTHESIZER_OPENAI_API_KEY`, `SYNTHESIZER_OPENAI_MODEL`
  (falls back to `LLM_MODEL_STANDARD`). `langchain-openai` added to `requirements.txt`.

## 0.2.0 - 2026-09-28

- Simplified to one function (`agent.py`): any input goes into the prompt, the LLM answers.
- Removed the multi-node graph, source numbering and citation handling. `graph.py` is now a one-node wrapper.

## 0.1.0 - 2026-09-28

- First version, following the platform agent contract (`{"task"}` in, `{"result"}` out, card, `GET /card`).
