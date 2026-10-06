"""respond: the final answer to the user in chat.

In order: the reply the supervisor set (its own answer, or why it stopped); else the answer of the final_answer
agent (role on its card); else the summaries of the steps, with any verifier warnings.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage

from orchestrator_agent.deps import DepsProvider
from orchestrator_agent.planning.roles import agents_with_role
from orchestrator_agent.state import OrchestratorState
from utils import Plan
from utils.events import emit


def make_respond(get_deps: DepsProvider):
    def respond(state: OrchestratorState) -> dict:
        text = state.get("final")
        if not text and state.get("plan"):
            cards = get_deps().registry.cards()
            plan = Plan.model_validate(state["plan"])
            results = state.get("results", {})
            finals = agents_with_role(cards, "final_answer")
            answers = [results[s.id]["output"] for s in plan.steps
                       if s.agent in finals and results.get(s.id, {}).get("status") == "ok"]
            if answers:
                text = answers[-1].get("answer") or answers[-1].get("summary")
            if not text:
                verifiers = agents_with_role(cards, "verifier")
                lines = [f"{s.agent}: {results[s.id]['output'].get('summary', results[s.id]['status'])}"
                         for s in plan.steps if s.id in results and s.agent not in verifiers]
                warnings = [w for s in plan.steps if s.agent in verifiers and s.id in results
                            for w in results[s.id]["output"].get("warnings", [])]
                text = "\n\n".join(lines) or "Done."
                if warnings:
                    text += "\n\nNote: " + "; ".join(warnings)
        text = text or "Done."
        emit("final", text=text)
        return {"final": text, "messages": [AIMessage(text)]}

    return respond
