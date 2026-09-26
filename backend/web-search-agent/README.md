# web-search-agent

**Owner:** Person A (team-search) · **Port:** 8201 · **Graph id:** `web_search` · **UI (planned):** `frontend/agents/web-search-ui` :4301

```
plan_queries -> Send(search x N, parallel) -> summarize
```

## Examples

| Input `task` | Output `result` |
|---|---|
| `{"objective": "What is the price of iPhone 16?"}` | `status: ok`, `findings[]`, `sources[]`, `summary` |
| `{"objective": "Find iPhone price in Oman", "params": {"query": "iPhone price", "region": "Oman"}}` | findings for "iPhone price in Oman" |

## Status / TODO

- Uses the offline **sample** search provider. Add a real one in `tools/search_provider.py` (`SEARCH_PROVIDER`).
- Optional LLM query planning with `LLM_MODEL_FAST`.

```powershell
cd backend\web-search-agent
langgraph dev --port 8201 --no-browser
```
