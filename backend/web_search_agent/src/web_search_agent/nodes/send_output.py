"""Last node: send the output (question + top 3 contents) to every route in ``WEB_SEARCH_VERIFIER_PATH`` found on the
network (e.g. the verifier's /verify and the synthesizer's /synthesize), in parallel - see services/handoff.py.

A route that cannot be found or reached does not fail this agent: its ``result`` is unchanged and the problem is
reported in the flow's "Send output" step and in the run details (``handoffs``: one record per URL).

The run is saved first (services/checkpoints.py), so "Retry" (``POST /custom/retry``) can run ``deliver_output`` again
later - also after a crash or a restart - without searching or calling the LLM.
"""

from __future__ import annotations

import asyncio
import logging
import time

from langgraph.config import get_stream_writer
from langgraph.runtime import get_runtime

from utils import AgentTask
from web_search_agent.context import Context
from web_search_agent.services import checkpoints, handoff, history
from web_search_agent.settings import get_settings
from web_search_agent.state import State
from web_search_agent.steps import StepReporter

logger = logging.getLogger(__name__)


async def deliver_output(step_id: str, result: dict, trace_id: str, reporter: StepReporter) -> dict:
    """Send the output; report the "Send output" step. Returns {"handoffs", "step", "warnings"}."""
    started = time.time()
    paths = get_settings().output_paths
    if not paths:
        step = reporter.report("verify", "skipped", "WEB_SEARCH_VERIFIER_PATH is empty - result returned to the caller")
        return {"handoffs": {}, "step": step["verify"], "warnings": []}

    reporter.report("verify", "running", f"Sending the question + top {len(result['findings'])} to "
                    f"{', '.join(paths)} on the network")
    try:
        records = await handoff.deliver(step_id, result)
    except Exception as exc:  # noqa: BLE001 - nothing found / unreachable must not fail the search
        error = f"{type(exc).__name__}: {exc}"[:300]
        logger.warning("[%s] output not sent: %s", trace_id, error)
        step = reporter.report("verify", "failed", error, duration_s=time.time() - started)
        return {"handoffs": {}, "step": step["verify"], "warnings": [f"output not sent: {error}"]}

    lines, items, ok = [], [], True
    for r in records:
        where = f"{r['path']} @ {r['host']}"
        if r["status"] == "failed":
            ok = False
            lines.append(f"{where}: {r['error']}")
        elif "passed" in r:
            ok = ok and r["passed"] is not False
            lines.append(f"{where}: {r.get('summary') or ('passed' if r['passed'] else 'failed')}")
            items += [f"{where}: {i}" for i in [*r.get("issues", []), *r.get("warnings", [])]]
        else:
            lines.append(f"{where}: sent")
    missing = [p for p in paths if p.lower() not in {r["path"].lower() for r in records}]
    if missing:
        lines.append(f"not found on the network: {', '.join(missing)}")
    step = reporter.report("verify", "done" if ok else "failed", " · ".join(lines), items,
                           duration_s=time.time() - started)
    warnings = [f"{r['path']} @ {r['host']} not reachable: {r['error'].split(':')[0]}"
                for r in records if r["status"] == "failed"]
    return {"handoffs": {r["url"]: r for r in records}, "step": step["verify"], "warnings": warnings}


def apply_delivery(details: dict, delivered: dict) -> dict:
    """The run details with a (new) delivery: steps, handoffs, verification (first verdict), warnings."""
    handoffs = delivered["handoffs"]
    verdict = next((h for h in handoffs.values() if "passed" in h), None)
    return {
        **details,
        "steps": [delivered["step"] if s["id"] == "verify" else s for s in details["steps"]],
        "handoffs": handoffs,
        "verification": verdict or {"status": "not_configured", "url": None},
        "warnings": [*details.get("warnings", []), *delivered["warnings"]],
    }


async def save_for_retry(state: State) -> None:
    """Keep what a retry needs; never fail the search because of it."""
    try:
        data = {key: state.get(key) for key in checkpoints.STATE_KEYS}
        await asyncio.to_thread(checkpoints.save, state["trace_id"], {"state": data, "details": state.get("details")})
    except (OSError, ValueError) as exc:
        logger.warning("[%s] run not saved - Retry will not be possible: %s", state.get("trace_id"), exc)


async def publish(details: dict, store=None) -> None:
    """Record the run for the UI: history, the saved run (for Retry), the LangGraph store (if any)."""
    history.record(details)
    try:
        await asyncio.to_thread(checkpoints.update, details["trace_id"], details=details)
    except (OSError, ValueError) as exc:
        logger.debug("saved run not updated: %s", exc)
    if store is not None:  # provided by the LangGraph server
        try:
            await store.aput(history.STORE_NAMESPACE, details["trace_id"], history.summary(details))
        except Exception as exc:  # noqa: BLE001 - history is best effort
            logger.debug("store write failed: %s", exc)


async def send_output(state: State) -> dict:
    runtime = get_runtime(Context)
    reporter = StepReporter(get_stream_writer())
    step_id = AgentTask.model_validate(state["task"]).task_id
    await save_for_retry(state)
    delivered = await deliver_output(step_id, state["result"], state["trace_id"], reporter)
    details = apply_delivery(state["details"], delivered)
    details["timings"] = {**details["timings"], "total_s": round(time.time() - state["started_at"], 2)}
    await publish(details, runtime.store)
    get_stream_writer()({"type": "result", "result": details})
    return {"details": details}
