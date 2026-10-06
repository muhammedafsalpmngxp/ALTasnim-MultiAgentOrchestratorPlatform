"""progress: the executor. Decides WHEN each step of the supervisor's plan runs (code, no LLM).

After every wave it looks at the plan and the results:
- a step was rejected by a human           -> stop and respond
- a step failed / a verifier failed        -> back to the supervisor (review mode) to revise the plan, or, with
                                              no replan left, to write the reply; a failed
                                              verification also rejects the steps it names (``rejected_steps``:
                                              marked failed, so the revised plan redoes only them; the others
                                              are reused) and says how to fix it (``fix``)
- steps whose dependencies are all done    -> run them now, in parallel: ``Send`` to the step's agent node
- nothing left                             -> respond; or the supervisor reviews first when no final_answer
                                              agent wrote the reply (it checks the results and writes it)

Verifiers and final answers are found by the agents' role (AgentCard.role), never by name.
"""

from __future__ import annotations

from langgraph.types import Command, Send

from orchestrator_agent.deps import DepsProvider
from orchestrator_agent.planning.roles import agents_with_role
from orchestrator_agent.state import OrchestratorState
from utils import Plan, StepStatus
from utils.events import now_iso

# A verifier's ``fix`` (verifier_agent card): what the revised plan should do.
FIXES = {
    "rewrite_answer": "the answer does not match the question. Keep the fact steps exactly as they are and run the "
                      "final answer again as a new step (new id) on the same steps; put what did not match into its "
                      "objective and question so the new answer responds to exactly what the user asked.",
    "find_more": "facts are missing or wrong. Keep the fact steps that were not rejected exactly as they are, add "
                 "steps that find only the missing or rejected parts, then the final answer again as a new step on "
                 "all of them.",
    "none": "the check itself could not run (no step was blamed). Finish if the results answer the request, or answer "
            "honestly with what was found.",
}


def rejected_by(output: dict, checked: list[str]) -> list[str]:
    """The steps a failed verifier rejects: those it names (``rejected_steps``, may be none), else (a verifier that
    does not name them) every step it checked."""
    named = output.get("rejected_steps")
    if isinstance(named, list):
        return [d for d in named if d in checked]
    return list(checked)


def make_progress(get_deps: DepsProvider):
    def progress(state: OrchestratorState) -> Command:
        deps = get_deps()
        cards = deps.registry.cards()
        plan = Plan.model_validate(state["plan"])
        steps = {s.id: s for s in plan.steps}
        results = {k: v for k, v in state.get("results", {}).items() if k in steps}
        replans = state.get("replans", 0)

        rejected = [k for k, v in results.items() if v["status"] == "rejected"]
        if rejected:
            reason = results[rejected[0]]["output"].get("summary", "rejected by approver")
            return Command(goto="respond", update={"final": f"Stopped: {reason}"})

        bad = {k: v for k, v in results.items() if v["status"] in ("failed", "revise")}
        if bad:
            feedback = [f"step {k} ({v['agent']}) {v['status']}: {v.get('error') or v['output'].get('summary', '')}"
                        for k, v in bad.items()]
            # A failed verification rejects the data it names: those steps are marked failed (the supervisor must
            # not reuse them) and named in the feedback, so the revised plan redoes only them.
            verifiers = agents_with_role(cards, "verifier")
            checked = {d: k for k in bad if steps[k].agent in verifiers
                       for d in rejected_by(bad[k]["output"], steps[k].depends_on)
                       if results.get(d, {}).get("status") == "ok"}
            feedback += [f"step {d} ({steps[d].agent}) failed verification by {k}: redo it (see {k} above)"
                         for d, k in checked.items()]
            feedback += [f"how to fix ({k}): {FIXES[fix]}" for k in bad if steps[k].agent in verifiers
                         if (fix := bad[k]["output"].get("fix")) in FIXES]
            # Also when no replan is left: the supervisor then writes the honest reply (what was tried, what was
            # found); a plan at that point ends the request with the failures (nodes/supervisor.py).
            update_results, update_status = {}, {}
            for d, k in checked.items():
                why = f"failed verification ({k}): rejected by the check, see its result"
                update_results[d] = {**results[d], "status": "failed", "error": why}
                update_status[d] = StepStatus(status="failed", agent=steps[d].agent, updated_at=now_iso(),
                                              detail=why).model_dump()
            return Command(goto="supervisor", update={
                "feedback": [*state.get("feedback", []), *feedback],  # all of this request's failures
                "review_reason": "failed",
                "results": update_results,
                "step_status": update_status,
            })

        done = {k for k, v in results.items() if v["status"] == "ok"}
        ready = [s for s in plan.steps
                 if s.id not in done and set(s.depends_on) | set(s.after) <= done]
        if not ready:
            if len(done) < len(steps):
                return Command(goto="respond", update={"final": "Plan is stuck: unresolved dependencies."})
            finals = agents_with_role(cards, "final_answer")
            if not any(steps[k].agent in finals for k in done):
                return Command(goto="supervisor", update={"review_reason": "complete"})
            return Command(goto="respond")

        running = {s.id: StepStatus(status="running", agent=s.agent, updated_at=now_iso()).model_dump()
                   for s in ready}
        sends = [
            Send("hitl_gate" if s.kind == "hitl" else s.agent, {
                "step": s.model_dump(),
                "deps": {d: state["results"][d]["output"] for d in s.depends_on},
                "attempt": replans,
                # Which request of the chat this is: a new question gets new agent threads (run_agent).
                "turn": sum(1 for m in state.get("messages", []) if m.type == "human"),
            })
            for s in ready
        ]
        return Command(goto=sends, update={"step_status": running})

    return progress
