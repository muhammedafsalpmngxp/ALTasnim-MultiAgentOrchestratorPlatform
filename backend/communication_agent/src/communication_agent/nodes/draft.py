"""Write the email from the outputs of the steps this step depends on (content.py, writer.py, render.py).

The user's own text (params.body) is sent exactly as written; otherwise the email is written from the earlier
steps' results. Invalid recipients, a recipient outside EMAIL_ALLOWED_DOMAINS, too many recipients, or nothing
to send end the step as failed (nothing reaches the approver). Recipients come only from the params, never
from the content.
"""

from __future__ import annotations

from typing import Literal

from langgraph.graph import END
from langgraph.types import Command
from pydantic import ValidationError

from communication_agent.card import CommunicationParams, EmailDraft
from communication_agent.content import collect
from communication_agent.render import text_to_html, to_html, to_text
from communication_agent.settings import Settings, get_settings
from communication_agent.state import State
from communication_agent.writer import write
from utils import AgentTask


def failed(summary: str) -> Command:
    return Command(goto=END, update={"result": {"status": "failed", "summary": summary}})


def check_recipients(addresses: list[str], settings: Settings) -> None:
    """ValueError when a recipient is not allowed (EMAIL_ALLOWED_DOMAINS) or there are too many."""
    if len(addresses) > settings.max_recipients:
        raise ValueError(f"{len(addresses)} recipients, at most {settings.max_recipients} (EMAIL_MAX_RECIPIENTS)")
    if settings.allowed_domains:
        outside = [a for a in addresses if a.rsplit("@", 1)[-1].lower() not in settings.allowed_domains]
        if outside:
            raise ValueError(f"not allowed (EMAIL_ALLOWED_DOMAINS): {', '.join(outside)}")


def _reason(exc: ValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, e['loc'])) or 'params'}: {e['msg']}" for e in exc.errors())


def draft(state: State) -> Command[Literal["approve", "__end__"]]:
    task = AgentTask.model_validate(state["task"])
    try:
        params = CommunicationParams.model_validate(task.params)
    except ValidationError as exc:
        return failed(f"Email not drafted: {_reason(exc)}")
    settings = get_settings()
    try:
        check_recipients([*params.to, *params.cc], settings)
    except ValueError as exc:
        return failed(f"Email not drafted: {exc}")

    if params.body and params.body.strip():  # the user wrote the email: sent exactly as written (no LLM, no additions)
        text = params.body.strip() + "\n"
        subject = (params.subject or f"Message from {settings.from_name}").strip()
        result = EmailDraft(to=params.to, cc=params.cc, subject=subject, body=text, html=text_to_html(text, subject),
                            writer="user", grounded=True)
        return Command(goto="approve", update={"draft": result.model_dump()})

    content = collect(task.inputs)
    if not content.text:
        return failed("Email not drafted: there is no content to send. Give the email text (params.body) or the "
                      "steps whose results it must contain (depends_on).")

    email, writer, grounded = write(task.objective, params, content, settings)
    text = to_text(email, settings.signature, content.sources, settings.from_name)
    html = to_html(email, settings.signature, content.sources, settings.from_name)
    result = EmailDraft(to=params.to, cc=params.cc, subject=email.subject, body=text, html=html,
                        sources=content.sources, writer=writer, grounded=grounded)
    return Command(goto="approve", update={"draft": result.model_dump()})
