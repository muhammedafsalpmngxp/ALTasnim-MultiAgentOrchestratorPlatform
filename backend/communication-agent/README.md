# communication-agent

**Owner:** Person B (team-comms) · **Port:** 8202 · **Graph id:** `communication` · **UI (planned):** `frontend/agents/communication-ui` :4302

```
draft -> approve (interrupt: human approves / edits / rejects) -> send (+ sent log in Store)
```

`approval_mode: internal`: the agent asks for approval itself; the orchestrator shows it in the approvals inbox.

## Resume values

```json
{"action": "approve"}
{"action": "edit", "edited": {"subject": "New subject", "body": "..."}}
{"action": "reject", "reason": "wrong recipient"}
```

## Channels

- `EMAIL_CHANNEL=console` (default): logs, sends nothing.
- `EMAIL_CHANNEL=smtp`: SMTP, e.g. Mailpit (`docker compose --profile mail up`) (UI http://localhost:8025).
- TODO: Microsoft Graph / Teams, LLM-polished drafts (`LLM_MODEL_STANDARD`).

```powershell
cd backend\communication-agent
langgraph dev --port 8202 --no-browser
```
