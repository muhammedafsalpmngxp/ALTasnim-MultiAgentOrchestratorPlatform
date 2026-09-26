# orchestrator-agent (supervisor)

**Owner:** platform lead · **Port:** 8100 · **Graph id:** `orchestrator`

Takes the user's request, **plans which agents run and in which order** (plan JSON), runs the plan
(parallel where possible), handles human approvals, and answers.

```
intake -> supervisor -> plan_guard -> progress --Send--> run_agent / hitl_gate --> progress ... -> respond
```

| Node | Does | LangGraph features |
|---|---|---|
| `supervisor` | answer / clarify / **plan** (`SupervisorDecision`) | structured output, `Command` |
| `clarify` | asks the user a question | `interrupt` |
| `plan_guard` | validates plan, inserts verifier/approval steps (code) | `Command`, custom stream event `plan` |
| `progress` | decides WHEN each step runs (dependencies), replans on failure | `Command(goto=[Send(...)])` |
| `run_agent` | runs one step on its agent deployment, bridges agent approvals | `langgraph_sdk`, `interrupt` |
| `hitl_gate` | plan-level human approval | `interrupt` |
| `respond` | final chat answer | messages |

## Config

- `config/agents.dev.yaml`: agents, their URLs/ports, and `transport` (`local` in-process | `remote` over HTTP).
- `config/policies.yaml`: max steps/replans, verification and approval rules, email allowlist.
- `backend/.env`: `AGENT_TRANSPORT`, `LLM_MODEL_STRONG` (without it, the rule-based planner is used).

## Planner

- `RulePlanner` (default, offline): price questions, "... then mail to x@y", "compare A and B", clarify.
- `LLMPlanner` (set `LLM_MODEL_STRONG`): prompt in `prompts/supervisor.md`, plans from agent cards.

Planner eval set: `evals/planning/dataset.jsonl`.
