# superviser_agent (supervisor / orchestrator)

**Owner:** platform lead · **Port:** 8100 · **Graph id:** `orchestrator`

Takes the user's request and **thinks with its own LLM** (`SUPERVISOR_LLM_MODEL`): which agents are needed, what
each one must do, and in which order. It writes that as the **plan** (`state["plan"]`, in the LangGraph state and
checkpoints, not a file), runs it (parallel where possible), reviews when something goes wrong, and answers. It is
one LangGraph graph, and **every agent is a node of it**: one node per enabled agent in `config/agents.*.yaml`.

```
intake -> supervisor -> plan_guard -> progress --Send--> rag | web_search | verifier | synthesizer | ... | hitl_gate
              ^                          ^                                                                 |
              |  review (on events)      +------------------------------ progress ... -> respond <---------+
              +------------------------- progress
```

| Node | Does | LangGraph features |
|---|---|---|
| `supervisor` | its LLM decides: **plan mode** answer / clarify / plan; **review mode** finish / plan v2 / clarify / answer | structured output, `Command` |
| `clarify` | asks the user a question | `interrupt` |
| `plan_guard` | checks the plan can run (known agents and steps, no cycle) | `Command`, custom stream event `plan` |
| `progress` | decides WHEN each step runs (`depends_on`); calls the supervisor again on events | `Command(goto=[Send(...)])` |
| `rag`, `web_search`, `verifier`, ... | one node per agent: runs a step on that agent (its own deployment, or in-process), bridges its approvals (`nodes/run_agent.py`) | `Send`, `langgraph_sdk`, `interrupt` |
| `hitl_gate` | plan-level human approval | `interrupt` |
| `respond` | final chat answer | messages |

## How the supervisor thinks (v1)

1. **Plan mode** (a new request). The LLM reads the request, the chat history and the **agent catalogue** built
   from every healthy agent's card: role, description, when to use / not to use, examples, params schema, returns.
   It fills, in order: `understanding` → `needs` → `reasoning` → `action` (answer | clarify | plan) → the plan
   (`goal`, `success_criteria`, steps with `agent`, `objective`, `params`, `depends_on`, `expected_output`).
   `depends_on` sets the order and what each step receives; steps without a dependency run in parallel. The LLM
   adds the verifier step itself (before the final answer).
2. The output schema is built per call: `agent` can only be an agent available right now. A plan that cannot run
   (unknown step in `depends_on`, a cycle, ...) goes back to the LLM with the errors (`max_plan_repairs`).
3. **Review mode**, only on events: a step failed, a verifier rejected data (those steps are marked failed and never
   reused), or the run ended without a `final_answer` agent. The LLM sees the plan, each step's status and result
   (short digest) and the failures, and decides: finish | plan v2 (same `plan_id`, version + 1; unchanged finished
   steps keep their results) | clarify | answer. With no replan left it writes the honest reply.

Prompts: `src/orchestrator_agent/prompts/supervisor_plan.md`, `supervisor_review.md`. They name no agent: everything
agent-specific comes from the cards, so a new agent needs no prompt or code change. Code: `planning/llm_supervisor.py`.
Agents are recognised by their **role** (`AgentCard.role`: source | transform | final_answer | verifier | action),
never by name.

v1 has no guardrails (no inserted verifier / approval steps, no step or email rules): they come back in v2. The
limits that end the loops stay: `max_replans`, `max_clarifications`, `max_plan_repairs` (`config/policies.yaml`).

## Config

- `backend/.env`, section superviser_agent: **`SUPERVISOR_LLM_MODEL`** (`<provider>:<model>`, a bare name means
  `openai:`; key `OPENAI_API_KEY`) and the optional `SUPERVISOR_LLM_*` settings (temperature, reasoning effort,
  timeout, retries, Responses API); see `.env.example`. Without a model the supervisor replies that it is not
  configured. The admin console shows the model (`GET /platform/admin/agents` → `supervisor.llm_model`).
- Every node is a LangGraph deployment: `{"task": AgentTask}` in, `{"result": {...}}` out, called on its port
  through its graph (`/threads/{id}/runs`). `config/agents.dev.yaml` lists them (`port`, `graph_id`) and the
  `transport` (`local` in-process | `remote` on their ports). `card` adds planning fields an agent's `GET /card`
  lacks (e.g. `role` for older agent images).
- `backend/.env`, OUTPUT: `AGENT_<NAME>=PORT` per agent (overrides the yaml), `AGENT_SUBNET` (networks searched; in
  Docker set your LAN), `AGENT_<NAME>_URL` to pin a machine. The machine of each agent is found on the network
  (`registry/discovery.py`): the first host with the port open whose LangGraph API serves the graph. On a shared
  LAN that can be a teammate's machine: pin `AGENT_<NAME>_URL` to use your own.

## Add an agent to the supervisor's planning

1. The agent (its team): a LangGraph graph with the platform contract and a **good card** at `GET /card`:
   description, `when_to_use`, `when_not_to_use`, examples (with params), `role`, `side_effects`, `params_schema`
   (with descriptions), `output_schema`. Its result always has `status` and `summary`.
2. `config/agents.dev.yaml`: an entry with `port` and `graph_id` (`enabled: true` when it is ready); restart the
   supervisor. It becomes a node and its card goes into the LLM's catalogue: nothing else changes here.
3. `backend/.env`: `AGENT_<NAME>=<port>`. Optional: tune its planning text in the admin console.
4. Add 2-3 questions for it to `evals/planning/dataset.jsonl`.

## Tests

- `pytest superviser_agent/tests`: no network, no LLM (a fake model and `ScriptedSupervisor`).
- Live planning with the real model (one LLM call per question of `evals/planning/dataset.jsonl`):
  `RUN_LIVE=1 pytest superviser_agent/tests/live` with `SUPERVISOR_LLM_MODEL` and `OPENAI_API_KEY` set.
