# communication-agent

**Owner:** team-comms · **Port:** 8202 · **Graph id:** `communication` · **UI:** `frontend/agents/communication-ui` (4302)

Sends an email with the results of earlier steps. The supervisor plans it only when the user asks to send something
(`role: action`, `side_effects: true`, `approval_mode: internal`).

```
draft  -> approve (interrupt: a human approves / edits / rejects) -> send
  |                  |
  +- failed          +- rejected            (nothing is sent)
```

| Node | Does |
|---|---|
| `draft` | checks the params (addresses, `EMAIL_ALLOWED_DOMAINS`, `EMAIL_MAX_RECIPIENTS`), takes the content of the earlier steps (`content.py`: the final answer, else the summaries / passages; verifier verdicts are not content) and writes the email (`writer.py`) |
| `approve` | `interrupt({"kind": "email_approval", "draft": ...})`; resume `{"action": "approve" \| "edit" \| "reject"}`. An edit is checked again; an edited body gets a new HTML version |
| `send` | sends once (the Message-ID comes from the run's thread; a retry or resume finds it in the store); a wrong login, refused recipient or unreachable server is a failed step with the reason |

## The email

- **Writer:** the LLM (`COMMUNICATION_LLM_MODEL`, key `OPENAI_API_KEY`, prompt `prompts/email_writer.md`) fills a
  structure: subject, greeting, opening, paragraphs / bullets / a table, closing. It may use only the content.
- **Grounding:** code checks every number and link of the LLM's email against the content (and the request). Not
  grounded: one retry with what is wrong; still not grounded, no model, or the LLM fails: the plain template.
- **Code adds:** the recipients (only from the params), the signature (`EMAIL_SIGNATURE`), the sources (from the
  results), and the footer. The email is sent as plain text + HTML (`render.py`: email-safe, inline CSS, escaped).

## Configuration (`backend/.env`)

| Variable | |
|---|---|
| `COMMUNICATION_LLM_MODEL` | e.g. `gpt-4o-mini` (a bare name means `openai:`); empty = the template |
| `EMAIL_DELIVERY` | `smtp` sends · `console` only logs (testing) |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USE_TLS` | Gmail: `smtp.gmail.com` / `587` / `true` (STARTTLS; port 465 = SSL) |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | the account and its **App Password** (Google Account → Security → 2-Step Verification → App passwords) |
| `EMAIL_FROM_NAME`, `EMAIL_SIGNATURE`, `EMAIL_FROM`, `EMAIL_REPLY_TO` | sender name, closing lines (`\n` = new line), sender address (default `SMTP_USERNAME`), reply address |
| `EMAIL_ALLOWED_DOMAINS`, `EMAIL_MAX_RECIPIENTS` | recipient rules (empty = any domain; default 10) |

Local test inbox without Gmail: `docker compose --profile mail up -d mailpit`, then `SMTP_HOST=mailpit`,
`SMTP_PORT=1025`, `SMTP_USE_TLS=false` and open http://localhost:8025.

## Routes (communication-ui)

`GET /card` · `GET /custom/status` (the email setup, never the password) · `GET /custom/sent` (emails sent since the
agent started, no bodies).

## Tests

`pytest communication-agent`: no network (a fake LLM and a fake SMTP server).
