"""rules: checks that need no LLM: there is an answer, it finished ok, and it is not empty."""

from __future__ import annotations

from verifier_agent.state import State


def rules(state: State) -> dict:
    answer = state.get("answer")
    if answer is None:
        return {"issues": ["nothing to verify: no answer among the inputs"]}
    step = answer["step"]
    if answer["shape"] != "object":
        return {"issues": [f"{step}: the answer is not an object"]}
    if answer["status"] not in (None, "ok"):
        return {"issues": [f"{step}: the answer step reported status '{answer['status']}'"]}
    if not answer["text"]:
        return {"issues": [f"{step}: the answer is empty"]}
    return {}
