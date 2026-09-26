"""Human approval before anything leaves the system (LangGraph ``interrupt``).

Resume value (sent by the Approvals UI through the orchestrator):
    {"action": "approve"}
    {"action": "edit", "edited": {"to": [...], "subject": "...", "body": "..."}}
    {"action": "reject", "reason": "..."}

This node does nothing before ``interrupt()``, so re-running it on resume is safe.
Sending happens in a separate node.
"""

from __future__ import annotations

from typing import Literal

from langgraph.graph import END
from langgraph.types import Command, interrupt

from communication_agent.card import EmailDraft
from communication_agent.state import State


def approve(state: State) -> Command[Literal["send", "__end__"]]:
    decision = interrupt({"kind": "email_approval", "agent": "communication", "draft": state["draft"]})
    action = (decision or {}).get("action", "reject")

    if action == "reject":
        reason = decision.get("reason", "rejected by approver")
        return Command(goto=END, update={"result": {"status": "rejected", "summary": f"Email not sent: {reason}"}})

    if action == "edit":
        edited = EmailDraft.model_validate({**state["draft"], **decision.get("edited", {})})
        return Command(goto="send", update={"draft": edited.model_dump()})

    return Command(goto="send")
