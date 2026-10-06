# Changelog

## 2.0.0 - 2026-10-06

- Simplified: checks only that the answer matches the question (every part answered, same topic). Reads only the
  question and the answer: no sources, no fact checking against evidence, no requests for more searches.
- An honest "not available" answer matches the question. Actions in the question ("and email it") never fail it.
- The verdict follows the parts and the topic (deterministic), not the model's own pass / fail.
- Result: `parts` (no evidence links), `missing`, `rejected_steps` (the answer), `fix` (rewrite_answer
  | none). Removed `claims`, `unsupported`, `find_more`.
- The supervisor checks only the final answer (no more check before an action).

## 1.0.0 - 2026-10-06

- Rebuilt: checks the request against the answer and ALL the evidence together, in one structured LLM call
  (`VERIFIER_LLM_MODEL`); comparisons across parallel steps now pass.
- Result says what to redo: `missing`, `unsupported`, `rejected_steps`, `fix` (rewrite_answer | find_more | none),
  plus `parts` and `claims`. `status` / `summary` / `passed` / `issues` / `warnings` unchanged.
- Run by the platform (the supervisor's plan_guard) after every final answer and before actions on found facts.
- Prompts in `prompts/*.md`. None-safe evidence reading (dict sources, answer-only outputs, chunks).
- An LLM error fails the check with a clear reason and blames no step (never a crash, never a silent pass).
- Removed: `POST /verify` push route, LAN discovery and forwarding to the synthesizer, `GET /ui`, the
  `VERIFIER_SYNTHESIZER_*` / `VERIFIER_DISCOVERY_SUBNETS` settings and the `LLM_MODEL_STANDARD` fallback.

## 0.1.0 - 2026-09-26

- Initial skeleton.
