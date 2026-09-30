"""progress: the executor. Decides WHEN each step runs (code, no LLM).

After every wave it looks at the plan and the results:
- a step was rejected by a human           -> stop and respond
- a step failed / verifier failed / revise -> back to the supervisor to replan (max N times); a failed
                                              verification also rejects the steps it checked (redone, e.g.
                                              rag's passages -> the replan uses web_search)
- steps whose dependencies are all done    -> run them now, in parallel: ``Send`` to the step's agent node
                                              (``web_search``, ``verifier``, ...) or to ``hitl_gate``
- nothing left                             -> respond
"""

from __future__ import annotations

from langgraph.types import Command, Send

from orchestrator_agent.deps import DepsProvider
from orchestrator_agent.state import OrchestratorState
from utils import Plan, StepStatus
from utils.events import now_iso


def make_progress(get_deps: DepsProvider):
    def progress(state: OrchestratorState) -> Command:
        deps = get_deps()
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
            # A failed verification rejects the data it checked (e.g. rag's passages): those steps are redone too,
            # and named in the feedback, so the next plan takes the facts from elsewhere (rag -> web_search).
            rejected = {d: k for k in bad if steps[k].agent == "verifier"
                        for d in steps[k].depends_on if results.get(d, {}).get("status") == "ok"}
            feedback += [f"step {d} ({steps[d].agent}) failed verification: {bad[k]['output'].get('summary', '')}"
                         for d, k in rejected.items()]
            if replans >= deps.policies.max_replans:
                return Command(goto="respond", update={
                    "feedback": feedback,
                    "final": "I could not complete the request:\n- " + "\n- ".join(feedback)})
            # Clear failed and rejected steps and every policy step (verifiers must re-check the new plan).
            clear = set(bad) | set(rejected) | {s.id for s in plan.steps if s.added_by == "policy"}
            return Command(goto="supervisor", update={
                "feedback": [*state.get("feedback", []), *feedback],  # all of this request's failures
                "replans": replans + 1,
                "results": {k: None for k in clear},
                "step_status": {k: None for k in clear},
            })

        done = {k for k, v in results.items() if v["status"] == "ok"}
        ready = [s for s in plan.steps
                 if s.id not in done and set(s.depends_on) | set(s.after) <= done]
        if not ready:
            if len(done) < len(steps):
                return Command(goto="respond", update={"final": "Plan is stuck: unresolved dependencies."})
            return Command(goto="respond")

        running = {s.id: StepStatus(status="running", agent=s.agent, updated_at=now_iso()).model_dump()
                   for s in ready}
        sends = [
            Send("hitl_gate" if s.kind == "hitl" else s.agent, {  # plan_guard: s.agent is a registered agent
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
