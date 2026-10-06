# verifier_agent

**Owner:** Person C (team-quality) · **Port:** 8203 · **Graph id:** `verifier` · **UI:** `frontend/agents/verifier-ui` :4303

```
(check_evidence || check_completeness || check_answer) -> verdict
```

The supervisor's LLM puts a verifier step after the steps that find facts and before the final answer (card
`role: verifier`). `status: failed` makes the supervisor review the plan; the data it rejected is never reused.

Checks:
- rule-based: failed inputs, empty findings, invalid source URLs, missing summaries (sample data is a **warning**);
- LLM judge (`check_answer`): does each input's content answer the question? Model: `VERIFIER_LLM_MODEL`
  (e.g. `openai:gpt-4o-mini`), else `LLM_MODEL_STANDARD`; neither set = skipped with a warning.

Known limitation: the judge checks every input against the whole question, so parallel steps that each cover one part
(e.g. one search per country in a comparison) are rejected. Judge the inputs together to fix it.

Custom routes (`api.py`): `GET /card`, `POST /verify` (plain HTTP callers, e.g. the web search agent's own output;
optionally forwards the verdict to the synthesizer: `VERIFIER_SYNTHESIZER_*` in `backend/.env`), `GET /verify/calls`
(the verifier UI), `GET /ui`.

```powershell
cd backend\verifier_agent
langgraph dev --port 8203 --no-browser
```
