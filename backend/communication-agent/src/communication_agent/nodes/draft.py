"""Write the email from the outputs of the steps this step depends on."""

from __future__ import annotations

from communication_agent.card import CommunicationParams, EmailDraft
from communication_agent.state import State
from utils import AgentTask


def draft(state: State) -> dict:
    task = AgentTask.model_validate(state["task"])
    params = CommunicationParams.model_validate(task.params)

    sections = [out.get("summary", "") for out in task.inputs.values() if isinstance(out, dict)]
    body = "Hello,\n\n" + "\n\n".join(s for s in sections if s) + "\n\nRegards,\nALTasnim Agent Platform"
    # TODO(team-comms): with get_model("standard"), rewrite `body` into a polished email.
    email = EmailDraft(to=params.to, subject=params.subject or task.objective[:120], body=body)
    return {"draft": email.model_dump()}
