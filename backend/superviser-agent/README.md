# superviser-agent (supervisor / orchestrator)

**Owner:** platform lead · **Port:** 8100 · **Graph id:** `orchestrator`

Takes the user's request, **plans which agents run and in which order** (plan JSON), runs the plan
(parallel where possible), handles human approvals, and answers. It is one LangGraph graph, and **every agent
is a node of it**: one node per enabled agent in `config/agents.*.yaml` (`web_search`, `communication`,
`verifier`, ...).

```
intake -> supervisor -> plan_guard -> progress --Send--> web_search | communication | verifier | ... | hitl_gate
                                         ^                                                              |
                                         +------------------------------ progress ... -> respond <------+
```

| Node | Does | LangGraph features |
|---|---|---|
| `supervisor` | answer / clarify / **plan** (`SupervisorDecision`) | structured output, `Command` |
| `clarify` | asks the user a question | `interrupt` |
| `plan_guard` | validates plan, inserts verifier/approval steps (code) | `Command`, custom stream event `plan` |
| `progress` | decides WHEN each step runs (dependencies), replans on failure | `Command(goto=[Send(...)])` |
| `web_search`, `communication`, `verifier`, ... | one node per agent: runs a step on that agent (in-process or its own deployment), bridges its approvals (`nodes/run_agent.py`) | `Send`, `langgraph_sdk`, `interrupt` |
| `hitl_gate` | plan-level human approval | `interrupt` |
| `respond` | final chat answer | messages |

## Flow

The supervisor controls it; the agents never call each other:

```
question -> rag (the user's documents) | web_search (the web) -> verifier -> synthesizer -> answer
            (rag found nothing -> replan with web_search)   (policy step)   (the reply)
```

## Config

- Every node is a LangGraph deployment: `{"task": AgentTask}` in, `{"result": {...}}` out, called on its port
  through its graph (`/threads/{id}/runs`). `config/agents.dev.yaml` lists them (`port`, `graph_id`) and the
  `transport` (`local` in-process | `remote` on their ports). `card` adds planning fields an agent's
  `GET /card` lacks. communication is disabled there (not part of the flow).
- `backend/.env`, section superviser-agent, OUTPUT: `AGENT_<NAME>=PORT` per agent (overrides the yaml),
  `AGENT_SUBNET` (networks searched; in Docker set your LAN), `AGENT_<NAME>_URL` to pin a machine.
- The machine of each agent is found on the network (`registry/discovery.py`): a host with the port open whose
  LangGraph API serves the graph (`POST /assistants/search`). Cached until a call to it fails.
- `config/policies.yaml`: max steps/replans, verification and approval rules, email allowlist.
- `backend/.env`: `AGENT_TRANSPORT`, `LLM_MODEL_STRONG` (without it, the rule-based planner is used).

## Planner

- `RulePlanner` (default, offline): price questions, "... then mail to x@y", "compare A and B", clarify.
- `LLMPlanner` (set `LLM_MODEL_STRONG`): prompt in `prompts/supervisor.md`, plans from agent cards.

Planner eval set: `evals/planning/dataset.jsonl`.
