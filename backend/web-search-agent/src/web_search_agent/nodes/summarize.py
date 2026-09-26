"""Merge the parallel search results into the agent's ``result``."""

from __future__ import annotations

from utils import AgentTask
from web_search_agent.state import State


def summarize(state: State) -> dict:
    task = AgentTask.model_validate(state["task"])
    findings = state.get("findings", [])[: state.get("max_sources", 5)]
    sources = list(dict.fromkeys(f["url"] for f in findings))

    if not findings:
        return {"result": {"status": "failed", "summary": f"No results for: {task.objective}",
                           "findings": [], "sources": []}}

    lines = [f"- {f['title']}: {f['snippet']} ({f['url']})" for f in findings]
    summary = f"{len(findings)} findings for '{task.objective}':\n" + "\n".join(lines)
    return {"result": {"status": "ok", "summary": summary, "findings": findings, "sources": sources}}
