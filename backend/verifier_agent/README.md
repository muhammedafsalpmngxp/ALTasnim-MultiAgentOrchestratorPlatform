# verifier_agent

**Owner:** Person C (team-quality) · **Port:** 8203 · **Graph id:** `verifier` · **UI:** `frontend/agents/verifier-ui` :4303

Checks ONE thing: **does the answer match the user's question?** It reads only the question and the answer. It does not
read sources, check facts or search anything.

- Every part of the question is answered ("compare Oman and UAE" → both prices). An honest "not available" counts as
  answered.
- The answer is about the same thing (the iPhone 16 Pro, not the iPhone 17; India, not the UAE).
- Actions in the question ("and email it") are done after the check and never fail it.

```
START -> collect -> rules (no LLM)  --+
                \-> judge (one LLM) --+-> verdict -> END
```

| Node | What it does |
|---|---|
| `collect` | the question (`params.request`) and the answer (`params.answer_step`); nothing else is read |
| `rules` | no LLM: there is an answer, its step finished ok, it is not empty |
| `judge` | ONE structured LLM call (`prompts/judge_system.md`, `prompts/judge_input.md`): the parts of the question, answered or not, and on topic or not |
| `verdict` | the code decides: pass when no rule failed, every fact part is answered and the answer is on topic |

## Who runs it

Only the supervisor, never its LLM: `plan_guard` adds a check step after every final answer
(`planning/checks.py`, found by role `verifier`, policy `verify_final`). A failed check sends the supervisor back to
write the answer again (the search steps are kept), at most `SUPERVISOR_MAX_REPLANS` times.

## Result

```json
{"status": "failed", "passed": false,
 "summary": "Verification failed: not answered: UAE price",
 "missing": ["UAE price"], "issues": ["not answered: UAE price"], "warnings": [],
 "rejected_steps": ["s3"], "fix": "rewrite_answer",
 "parts": [{"part": "Oman price", "kind": "fact", "answered": true},
           {"part": "UAE price", "kind": "fact", "answered": false}],
 "checked": {"answer_step": "s3", "model": "openai:gpt-5.6-luna"}}
```

When the check itself cannot run (LLM error) it fails with the reason and blames nothing (`fix: none`).

## Settings (`backend/.env`, section verifier_agent)

```
VERIFIER_PORT=8203
VERIFIER_LLM_MODEL=openai:gpt-5.6-luna   # a bare name = openai:<name>; empty = rule checks only, with a warning
```

Timeout (60 s) and retries (2) are fixed in `settings.py`.

## Routes (`api.py`)

`GET /card` · `GET /verify/status` (the checking model) · `GET /verify/calls` / `DELETE /verify/calls` (the last 50
verdicts, for verifier-ui). The LangGraph API (`/threads`, `/runs`) is for the supervisor only (`auth.py`).

## Run and test

```powershell
cd backend\verifier_agent
langgraph dev --port 8203 --no-browser
```

```bash
pytest verifier_agent/tests                                       # fake judge, no network
RUN_LIVE=1 ENV_FILE=/app/.env pytest verifier_agent/tests/live    # the real model, 11 cases
```
