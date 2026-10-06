"""verdict: the rule issues + the judge's output -> the result (no LLM).

The code has the last word: the check passes only when no rule failed AND every fact part of the question is
answered AND the answer is on topic (the judge's own pass / fail is not used). On a fail the answer step is rejected
and ``fix`` is ``rewrite_answer``; when the check itself could not run (LLM error) nothing is rejected and ``fix``
is ``none``.
"""

from __future__ import annotations

import time

from verifier_agent import calls, settings
from verifier_agent.card import VerifyResult
from verifier_agent.nodes.judge import Judgement
from verifier_agent.state import State


def _result(state: State) -> VerifyResult:
    answer = state.get("answer")
    answer_step = answer["step"] if answer else None
    issues = list(state.get("issues") or [])
    rule_failed = bool(issues)
    warnings = list(state.get("warnings") or [])
    error = state.get("judge_error")
    j = Judgement.model_validate(state["judgement"]) if state.get("judgement") else None

    parts = j.parts if j else []
    missing = [p.part for p in parts if p.kind == "fact" and not p.answered]  # an action is done after the check
    if error:
        issues.append(f"verification could not run: {error}")
    if j:
        issues += [f"not answered: {m}" for m in missing]
        if not j.on_topic:
            issues.append(f"off topic: {j.summary}" if j.summary else "the answer is not about what the user asked")
        # The verdict follows the parts and the topic, not the judge's own pass / fail: a fail it cannot tie to a
        # part or the topic (e.g. an email that is sent after the check) is not a mismatch.

    passed = not issues
    blamed = not passed and (rule_failed or not error)  # an LLM error alone blames nobody
    if passed:
        summary = f"Verified: {j.summary}" if j and j.summary else "Verification passed"
        if not j and not error:
            summary += " (rule checks only)"
    else:
        summary = "Verification failed: " + "; ".join(issues)
    if warnings:
        summary += " (warnings: " + "; ".join(warnings) + ")"
    return VerifyResult(
        status="ok" if passed else "failed", passed=passed, summary=summary, issues=issues, warnings=warnings,
        missing=missing, parts=parts,
        rejected_steps=[answer_step] if blamed and answer_step else [],
        fix="rewrite_answer" if blamed and answer_step else "none",
        checked={"answer_step": answer_step, "model": settings.model_name()})


def verdict(state: State) -> dict:
    result = _result(state).model_dump()
    started = state.get("started")
    calls.record(state, result, (time.perf_counter() - started) if started else None)
    return {"result": result}
