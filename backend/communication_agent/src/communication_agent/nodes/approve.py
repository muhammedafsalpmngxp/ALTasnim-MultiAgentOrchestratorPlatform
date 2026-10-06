"""Human approval before anything leaves the system (LangGraph ``interrupt``).

Resume value (sent by the Approvals UI through the orchestrator):
    {"action": "approve"}
    {"action": "edit", "edited": {"to": [...], "cc": [...], "subject": "...", "body": "..."}}
    {"action": "reject", "reason": "..."}

An edit is checked like the draft (addresses, EMAIL_ALLOWED_DOMAINS, EMAIL_MAX_RECIPIENTS); an edited body gets a
new HTML version from the edited text. This node does nothing before ``interrupt()``, so re-running it on resume is
safe. Sending happens in a separate node.
"""

from __future__ import annotations

from typing import Literal

from langgraph.graph import END
from langgraph.types import Command, interrupt
from pydantic import ValidationError

from communication_agent.card import EmailDraft
from communication_agent.nodes.draft import check_recipients, failed
from communication_agent.render import text_to_html
from communication_agent.settings import get_settings
from communication_agent.state import State

EDITABLE = ("to", "cc", "subject", "body")


def approve(state: State) -> Command[Literal["send", "__end__"]]:
    decision = interrupt({"kind": "email_approval", "agent": "communication", "draft": state["draft"]})
    decision = decision if isinstance(decision, dict) else {}
    action = decision.get("action", "reject")

    if action == "reject":
        reason = decision.get("reason") or "rejected by approver"
        return Command(goto=END, update={"result": {"status": "rejected", "summary": f"Email not sent: {reason}"}})

    if action == "edit":
        changes = {k: v for k, v in (decision.get("edited") or {}).items() if k in EDITABLE}
        try:
            edited = EmailDraft.model_validate({**state["draft"], **changes})
            check_recipients([*edited.to, *edited.cc], get_settings())
        except (ValidationError, ValueError) as exc:
            return failed(f"Email not sent: the edited email is invalid: {exc}")
        if "body" in changes and changes["body"] != state["draft"].get("body"):
            edited = edited.model_copy(update={"html": text_to_html(edited.body, edited.subject)})
        return Command(goto="send", update={"draft": edited.model_dump()})

    return Command(goto="send")
