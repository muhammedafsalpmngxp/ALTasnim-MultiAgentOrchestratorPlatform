# Changelog

## 1.0.0 - 2026-10-05

- Supervisor v1: its own LLM (`SUPERVISOR_LLM_MODEL`) plans the flow from the agents' cards (plan mode) and reviews
  on events (a step failed, a verifier rejected data, no final answer yet). Agents are recognised by their role.
- Removed the rule-based planner, the unused tiered LLM planner and the policy steps (guardrails come back in v2).

## 0.1.0 - 2026-09-26

- Initial skeleton.
