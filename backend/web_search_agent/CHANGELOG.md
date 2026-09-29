# Changelog

## 2.0.0 - 2026-09-28

Real web search agent (from the standalone MICROFRONT project), in the platform's agent layout.

- Graph `web_search`: `plan_queries -> Send(search x N) -> select_pages -> Send(extract x M) -> rank -> finalize
  -> send_output`.
  Live search (Google -> Tavily -> DuckDuckGo, + Wikipedia), Trafilatura extraction, BM25 + cross-encoder reranking,
  OpenAI query planning.
- Platform contract: input `{"task": AgentTask}` (params `query`, `region`, `freshness`, `include_domains`,
  `exclude_domains`), output `{"result": {status, summary, question, findings, sources}}` - only the question and
  the top 3 contents go to the verifier.
- Reads upstream results (e.g. the RAG agent) from `task.inputs`: `search_query(ies)` are searched, `answer` /
  `summary` guide the query planner.
- No summarizer / LLM answer: the output is the question and the top 3 contents; the verifier takes it from there.
- Output: `WEB_SEARCH_VERIFIER_PATH=/verify,/synthesize` - POSTed to every machine of the network that has one of
  these routes (OpenAPI spec / 405 probe), in parallel; shared scan, retries for flapping links; one body for
  the verifier (`task`) and the synthesizer (`question`, `inputs`).
- "Retry" (`POST /custom/retry`, UI buttons on the Send output step, the result and Recent runs): sends another
  request to the output agents with the saved run (`logs/checkpoints/`) - no search, no LLM.
- `run.py` + `runlog.py`: human-readable log, `FRONTEND | BACKEND` columns.
- Sources: Wikipedia API on every search (2 best articles), optional Google Programmable Search, social
  media / video / forums blocked, trusted sites (Wikipedia, major news, gov, edu) read first and boosted;
  fewer sources (8 results, 4 pages), top 3 from different pages.
- Reranker `cross-encoder/ms-marco-MiniLM-L-6-v2` (4x faster than bge-reranker-base on CPU), downloaded
  once into `models/` and loaded from there.
- Settings prefixed `WEB_SEARCH_` in the shared `backend/.env`; `sample` provider (default) runs offline.
- Nodes are async; `dual()` also supports the sync `graph.invoke` used by `utils.testing`.
- UI routes `/custom/search/stream`, `/custom/history`, `/custom/sources`, `/custom/health`; `GET /card`.

## 0.1.0 - 2026-09-26

- Initial skeleton.
