"""Send the approved email once and record it in the LangGraph Store (sent log, no body).

The Message-ID comes from this run's thread: a retry of this node, or a resume of the run, finds the record and
does not send again. A failure (wrong login, refused recipient, server down) is a failed step with the reason.
"""

from __future__ import annotations

from langgraph.config import get_config
from langgraph.runtime import Runtime

from communication_agent.card import EmailDraft
from communication_agent.channels.email import EmailError, message_id_for, send_email
from communication_agent.settings import get_settings
from communication_agent.state import State
from utils import RequestContext
from utils.context import ctx_or_default


def _result(email: EmailDraft, message_id: str, delivery: str) -> dict:
    note = "" if delivery == "smtp" else " (EMAIL_DELIVERY=console: logged only, not delivered)"
    return {"result": {
        "status": "ok",
        "delivery": "sent",
        "channel": delivery,
        "message_id": message_id,
        "to": email.to,
        "cc": email.cc,
        "subject": email.subject,
        "writer": email.writer,
        "summary": f"Email '{email.subject}' sent to {', '.join(email.to)}{note}",
    }}


def send(state: State, runtime: Runtime[RequestContext]) -> dict:
    email = EmailDraft.model_validate(state["draft"])
    settings = get_settings()
    thread = (get_config().get("configurable") or {}).get("thread_id")
    message_id = message_id_for(str(thread) if thread else None, settings.from_address)
    namespace = ("sent", ctx_or_default(runtime.context)["tenant_id"])

    if runtime.store is not None and (done := runtime.store.get(namespace, message_id)):  # already sent
        return _result(email, message_id, done.value.get("delivery", settings.delivery))
    email = email.model_copy(update={"message_id": message_id})
    try:
        message_id = send_email(email)
    except EmailError as exc:
        return {"result": {"status": "failed", "summary": f"Email not sent: {exc}"}}

    if runtime.store is not None:  # provided by Agent Server; None in plain unit tests
        runtime.store.put(namespace, message_id, {"to": email.to, "cc": email.cc, "subject": email.subject,
                                                  "writer": email.writer, "delivery": settings.delivery})
    return _result(email, message_id, settings.delivery)
