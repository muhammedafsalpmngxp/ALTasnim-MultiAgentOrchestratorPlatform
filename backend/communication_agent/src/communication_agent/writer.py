"""Writes the email: the LLM (COMMUNICATION_LLM_MODEL) turns the content into a professional email; code checks
that every number and link it wrote is in the content (grounding). One retry with the mismatches; still not
grounded, no model, or the LLM fails -> the plain template, so an invented fact is never sent."""

from __future__ import annotations

import logging
import re
from datetime import date
from functools import lru_cache
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from communication_agent.card import CommunicationParams
from communication_agent.content import URL_RE, Content
from communication_agent.render import EmailContent
from communication_agent.settings import Settings

log = logging.getLogger(__name__)

PROMPT = (Path(__file__).parent / "prompts" / "email_writer.md").read_text(encoding="utf-8")
NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


@lru_cache(maxsize=4)
def _model(name: str):
    from langchain.chat_models import init_chat_model

    full = name if ":" in name else f"openai:{name}"
    kwargs: dict = {"timeout": 60.0, "max_retries": 2}
    if full.split(":", 1)[0] in ("openai", "azure_openai"):
        kwargs["use_responses_api"] = True  # reasoning models (gpt-5.x) take tools only on the Responses API
    return init_chat_model(full, **kwargs)


def _numbers(text: str) -> set[str]:
    """Numbers with 2+ digits, normalised ('3,399.00' -> '3399')."""
    out = set()
    for raw in NUMBER_RE.findall(text):
        value = raw.replace(",", "")
        if "." in value:
            value = value.rstrip("0").rstrip(".")
        if sum(c.isdigit() for c in value) >= 2:
            out.add(value)
    return out


def _urls(text: str) -> set[str]:
    return {u.rstrip(".,;:") for u in URL_RE.findall(text)}


def email_text(email: EmailContent) -> str:
    table = [*(email.table.headers if email.table else []), *(c for r in (email.table.rows if email.table else [])
                                                               for c in r)]
    return "\n".join([email.subject, email.greeting, email.opening, *email.paragraphs, *email.bullets, *table,
                      email.closing])


def ungrounded(email: EmailContent, allowed: str) -> list[str]:
    """Numbers and links in the email that are not in the allowed text (empty: grounded)."""
    text = email_text(email)
    numbers = sorted(_numbers(text) - _numbers(allowed))
    links = sorted(_urls(text) - _urls(allowed))
    return [*(f"number {n}" for n in numbers), *(f"link {u}" for u in links)]


def _allowed_text(task_objective: str, params: CommunicationParams, content: Content, today: date) -> str:
    """Everything the email may quote: the content, its sources, the request, and today's date."""
    return "\n".join([content.text, *content.sources, task_objective, params.subject or "",
                      params.instructions or "", params.recipient_name or "", today.isoformat(),
                      today.strftime("%d %B %Y")])


def _request(task_objective: str, params: CommunicationParams, content: Content, today: date) -> str:
    return "\n\n".join([
        f"TODAY: {today.strftime('%d %B %Y')}",
        f"WHAT THE USER ASKED FOR: {task_objective}",
        f"RECIPIENT NAME: {params.recipient_name or '(not given)'}",
        f"SUBJECT GIVEN BY THE USER: {params.subject or '(none: write one)'}",
        f"TONE: {params.tone}",
        f"LANGUAGE: {params.language or '(the language of the request)'}",
        f"INSTRUCTIONS ABOUT THE EMAIL: {params.instructions or '(none)'}",
        "CONTENT (the only facts you may use):\n<<<\n" + content.text + "\n>>>",
    ])


def template(task_objective: str, params: CommunicationParams, content: Content, settings: Settings) -> EmailContent:
    """No LLM: the content as it is, in the same professional layout."""
    name = params.recipient_name
    return EmailContent(
        subject=(params.subject or f"Requested information from {settings.from_name}")[:120],
        greeting=f"Dear {name}," if name else "Hello,",
        opening="Please find below the information you requested.",
        paragraphs=[p.strip() for p in re.split(r"\n\s*\n", content.text) if p.strip()],
        closing="Please let me know if you need further details.",
    )


def write(task_objective: str, params: CommunicationParams, content: Content,
          settings: Settings) -> tuple[EmailContent, str, bool]:
    """(the email, writer: llm | template, grounded)."""
    today = date.today()
    if not settings.llm_model:
        return template(task_objective, params, content, settings), "template", True
    allowed = _allowed_text(task_objective, params, content, today)
    try:
        llm = _model(settings.llm_model).with_structured_output(EmailContent, method="function_calling")
        messages = [SystemMessage(PROMPT), HumanMessage(_request(task_objective, params, content, today))]
        for attempt in range(2):
            email = llm.invoke(messages)
            if params.subject:  # the user's own subject is kept as given
                email = email.model_copy(update={"subject": params.subject})
            problems = ungrounded(email, allowed)
            if not problems:
                return email, "llm", True
            log.warning("email draft not grounded (attempt %d): %s", attempt + 1, problems)
            messages += [AIMessage(email.model_dump_json()), HumanMessage(
                "These are not in the CONTENT: " + "; ".join(problems)
                + ". Remove them or copy them exactly from the CONTENT, and return the whole email again.")]
    except Exception as exc:  # noqa: BLE001 - no key, API error, timeout: the template still sends the content
        log.warning("email writer LLM failed, using the template: %s: %s", type(exc).__name__, exc)
    return template(task_objective, params, content, settings), "template", True
