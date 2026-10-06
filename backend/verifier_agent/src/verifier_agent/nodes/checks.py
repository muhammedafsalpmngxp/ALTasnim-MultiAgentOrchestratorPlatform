"""Three independent checks. They run in parallel (static fan-out edges from START)."""

from __future__ import annotations

import logging
import os

from pydantic import BaseModel, Field

from utils import AgentTask
from utils.llm import get_model
from verifier_agent.state import State

logger = logging.getLogger(__name__)

MAX_EVIDENCE_CHARS = 12000  # what the LLM judge reads per step


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
        if "chunks" in out and not out["chunks"]:
            issues.append(f"{step_id}: no chunks")
        bad = [u for u in out.get("sources", []) if not str(u).startswith(("http://", "https://"))]
        if bad:
            issues.append(f"{step_id}: invalid source URLs {bad}")
        if "[SAMPLE DATA]" in str(out.get("summary", "")):
            warnings.append(f"{step_id}: uses sample data (no real search provider configured)")
    return {"issues": issues, "warnings": warnings}


def check_completeness(state: State) -> dict:
    task = AgentTask.model_validate(state["task"])
    issues = []
    if not task.inputs:
        issues.append("nothing to verify: no inputs from earlier steps")
    for step_id, out in task.inputs.items():
        if isinstance(out, dict) and not evidence_text(out):
            issues.append(f"{step_id}: no content (summary, findings or chunks)")
    return {"issues": issues}


class Judgement(BaseModel):
    verified: bool = Field(description="True if the content answers the question and makes sense for it")
    reason: str = Field(description="One or two sentences: why it does or does not answer the question")


JUDGE_PROMPT = """You verify the output of a retrieval agent (document search or web search).
Decide whether the content below actually answers the user's question and makes sense for it.
- verified = true: the content is on topic and contains the information the question asks for.
- verified = false: the content is off topic, does not contain the answer, or contradicts itself.
Judge only from the content. Do not use outside knowledge to fill gaps.

Question: {question}

Content:
{content}"""


def check_answer(state: State) -> dict:
    """LLM-as-judge: does each step's content answer the question? Skipped (warning) without a model."""
    task = AgentTask.model_validate(state["task"])
    steps = {sid: evidence_text(out) for sid, out in task.inputs.items() if isinstance(out, dict)}
    steps = {sid: text for sid, text in steps.items() if text}
    if not steps:
        return {}
    model = judge_model()
    if model is None:
        return {"warnings": ["answer check skipped: no LLM configured (VERIFIER_LLM_MODEL or LLM_MODEL_STANDARD)"]}
    judge = model.with_structured_output(Judgement)
    question = task_question(task)
    issues, warnings, judgements = [], [], {}
    for step_id, text in steps.items():
        try:
            j = judge.invoke(JUDGE_PROMPT.format(question=question, content=text[:MAX_EVIDENCE_CHARS]))
        except Exception as exc:  # a failing LLM must not fail the rule-based verdict
            logger.warning("answer check for %s failed: %s", step_id, exc)
            warnings.append(f"{step_id}: answer check failed ({type(exc).__name__})")
            continue
        judgements[step_id] = j.model_dump()
        if not j.verified:
            issues.append(f"{step_id}: content does not answer the question: {j.reason}")
    return {"issues": issues, "warnings": warnings, "judgements": judgements}


def verdict(state: State) -> dict:
    issues, warnings = state.get("issues", []), state.get("warnings", [])
    passed = not issues
    summary = "Verification passed" if passed else "Verification failed: " + "; ".join(issues)
    if warnings:
        summary += " (warnings: " + "; ".join(warnings) + ")"
    return {"result": {"status": "ok" if passed else "failed", "passed": passed,
                       "issues": issues, "warnings": warnings, "judgements": state.get("judgements", {}),
                       "summary": summary}}


def judge_model():
    """VERIFIER_LLM_MODEL (e.g. openai:gpt-4o-mini), else the platform's standard model, else None."""
    name = os.getenv("VERIFIER_LLM_MODEL")
    if not name:
        return get_model("standard")
    from langchain.chat_models import init_chat_model

    return init_chat_model(name, temperature=0)


def task_question(task: AgentTask) -> str:
    for out in task.inputs.values():
        if isinstance(out, dict) and out.get("question"):
            return str(out["question"])
    return task.objective


def evidence_text(out: dict) -> str:
    """The step's content: its summary, else its findings' / chunks' text (RAG sends chunks, no summary)."""
    summary = str(out.get("summary") or "").strip()
    if summary:
        return summary
    parts = []
    for item in [*(out.get("findings") or []), *(out.get("chunks") or [])]:
        if isinstance(item, dict):
            text = item.get("content") or item.get("text") or item.get("snippet") or ""
            label = item.get("title") or item.get("document_name") or ""
            if str(text).strip():
                parts.append(f"[{label}] {text}" if label else str(text))
        elif str(item).strip():
            parts.append(str(item))
    return "\n\n".join(parts).strip()
