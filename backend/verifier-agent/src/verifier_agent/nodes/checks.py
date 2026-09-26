"""Two independent checks. They run in parallel (static fan-out edges from START)."""

from __future__ import annotations

from utils import AgentTask
from verifier_agent.state import State


def check_evidence(state: State) -> dict:
    task = AgentTask.model_validate(state["task"])
    issues, warnings = [], []
    for step_id, out in task.inputs.items():
        if not isinstance(out, dict):
            issues.append(f"{step_id}: output is not an object")
            continue
        if out.get("status") not in (None, "ok"):
            issues.append(f"{step_id}: step reported status '{out.get('status')}'")
        if "findings" in out and not out["findings"]:
            issues.append(f"{step_id}: no findings")
        bad = [u for u in out.get("sources", []) if not str(u).startswith(("http://", "https://"))]
        if bad:
            issues.append(f"{step_id}: invalid source URLs {bad}")
        if "[SAMPLE DATA]" in str(out.get("summary", "")):
            warnings.append(f"{step_id}: uses sample data (no real search provider configured)")
    # TODO(team-quality): LLM-as-judge fact check with get_model("standard").
    return {"issues": issues, "warnings": warnings}


def check_completeness(state: State) -> dict:
    task = AgentTask.model_validate(state["task"])
    issues = []
    if not task.inputs:
        issues.append("nothing to verify: no inputs from earlier steps")
    for step_id, out in task.inputs.items():
        if isinstance(out, dict) and not str(out.get("summary", "")).strip():
            issues.append(f"{step_id}: missing summary")
    return {"issues": issues}


def verdict(state: State) -> dict:
    issues, warnings = state.get("issues", []), state.get("warnings", [])
    passed = not issues
    summary = "Verification passed" if passed else "Verification failed: " + "; ".join(issues)
    if warnings:
        summary += " (warnings: " + "; ".join(warnings) + ")"
    return {"result": {"status": "ok" if passed else "failed", "passed": passed,
                       "issues": issues, "warnings": warnings, "summary": summary}}
