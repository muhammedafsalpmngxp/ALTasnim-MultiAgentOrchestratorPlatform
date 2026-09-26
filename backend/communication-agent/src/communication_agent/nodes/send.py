"""Send the approved email and record it in the LangGraph Store (sent log)."""

from __future__ import annotations

from langgraph.runtime import Runtime

from communication_agent.card import EmailDraft
from communication_agent.channels.email import send_email
from communication_agent.state import State
from utils import RequestContext
from utils.context import ctx_or_default


def send(state: State, runtime: Runtime[RequestContext]) -> dict:
    email = EmailDraft.model_validate(state["draft"])
    message_id = send_email(email)

    if runtime.store is not None:  # provided by Agent Server; None in plain unit tests
        tenant = ctx_or_default(runtime.context)["tenant_id"]
        runtime.store.put(("sent", tenant), message_id, email.model_dump())

    return {"result": {
        "status": "ok",
        "delivery": "sent",
        "message_id": message_id,
        "to": email.to,
        "subject": email.subject,
        "summary": f"Email '{email.subject}' sent to {', '.join(email.to)}",
    }}
