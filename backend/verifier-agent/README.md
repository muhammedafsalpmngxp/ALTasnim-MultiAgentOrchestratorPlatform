# verifier-agent

**Owner:** Person C (team-quality) · **Port:** 8203 · **Graph id:** `verifier` · **UI (planned):** `frontend/agents/verifier-ui` :4303

```
(check_evidence || check_completeness) -> verdict
```

Inserted automatically by the orchestrator's policy before any human approval, and at the end of plans
that have no verifier. `status: failed` makes the orchestrator replan.

Checks today (rule-based): failed inputs, empty findings, invalid source URLs, missing summaries.
Sample data is reported as a **warning**, not a failure.
TODO: LLM-as-judge fact check (`LLM_MODEL_STANDARD`).

```powershell
cd backend\verifier-agent
langgraph dev --port 8203 --no-browser
```
