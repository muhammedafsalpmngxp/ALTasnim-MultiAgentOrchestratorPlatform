"""What this agent does (GET /card), what the supervisor sends it (params) and the email it drafts."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from utils import AgentCard

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")


def clean_addresses(values: list[str]) -> list[str]:
    """Trimmed, de-duplicated addresses; ValueError names any that is not an email address."""
    out = list(dict.fromkeys(v.strip() for v in values if v and v.strip()))
    if bad := [v for v in out if not EMAIL_RE.match(v)]:
        raise ValueError(f"not an email address: {', '.join(bad)}")
    return out


class CommunicationParams(BaseModel):
    channel: Literal["email"] = "email"
    to: list[str] = Field(min_length=1, description="Recipient email addresses, exactly as the user gave them.")
    cc: list[str] = Field(default_factory=list, description="CC email addresses, only if the user asked for them.")
    subject: str | None = Field(default=None, description="Subject line, only if the user gave one; else written.")
    recipient_name: str | None = Field(default=None, description="The recipient's name, only if the user said it.")
    tone: Literal["formal", "friendly"] = Field("formal", description="formal (default) or friendly.")
    language: str | None = Field(default=None, description="Language of the email, e.g. English or Arabic "
                                                            "(default: the language of the request).")
    instructions: str | None = Field(default=None, description="Anything else the user asked about the email "
                                                               "(e.g. 'keep it short', 'mention the deadline').")
    body: str | None = Field(default=None, description=(
        "The complete email text the user wrote themselves, copied verbatim (every line, including any greeting, "
        "signature and links). Only when the user supplied the text; then it is sent exactly as written and no "
        "earlier step is needed. Leave it empty when the email must be written from the results of earlier steps."))

    @field_validator("to", "cc")
    @classmethod
    def check_addresses(cls, value: list[str]) -> list[str]:
        return clean_addresses(value)


class EmailDraft(BaseModel):
    """The email the approver sees (and edits) and the agent sends."""

    to: list[str]
    cc: list[str] = Field(default_factory=list)
    subject: str
    body: str  # plain text (what the approver edits)
    html: str = ""  # the HTML version (rebuilt from the text after an edit)
    sources: list[str] = Field(default_factory=list)
    writer: Literal["llm", "template", "user"] = "template"  # who wrote it (user = the user's own text, verbatim)
    grounded: bool = True  # every number and link in it is in the content of the earlier steps
    message_id: str = ""  # set just before sending (stable per run, so a retry is recognised)

    @field_validator("to", "cc")
    @classmethod
    def check_addresses(cls, value: list[str]) -> list[str]:
        return clean_addresses(value)


CARD = AgentCard(
    name="communication",
    version="1.1.0",
    description=(
        "Sends an email. Either the user gives the text (params.body: sent exactly as written), or it writes a "
        "professional email (subject, greeting, body, signature, sources) from the results of earlier steps only. "
        "A human approves or edits the draft before it is sent."
    ),
    when_to_use=(
        "The user explicitly asks to email, mail, send, share or forward something to someone (an email address). "
        "If the user wrote the email text, put it in params.body and use this agent alone (no other step). If the "
        "email must contain information to be found, put this agent AFTER the steps that produce it (depends_on "
        "them, usually the final answer step). Recipients, cc and subject always from the request."
    ),
    when_not_to_use=(
        "Finding or checking information (use a source / verifier agent), answering the user in chat (the "
        "supervisor does that), or when no recipient address is known (clarify with the user first)."
    ),
    examples=[
        "Find the iPhone 16 price in Oman and email it to rijin@gmail.com (params: to=['rijin@gmail.com'])",
        "Email the comparison to sara@altasnim.com and cc ali@altasnim.com, keep it short "
        "(params: to=['sara@altasnim.com'], cc=['ali@altasnim.com'], instructions='keep it short')",
        "Send the retention money clause to Ahmed at ahmed@company.com in Arabic "
        "(params: to=['ahmed@company.com'], recipient_name='Ahmed', language='Arabic')",
        "Send this mail to sara@company.com, subject 'Meeting moved', content: Hello Sara, the meeting is now at 3 pm. "
        "Regards, Ali (params: to=['sara@company.com'], subject='Meeting moved', body='Hello Sara, the meeting is "
        "now at 3 pm. Regards, Ali' with the user's line breaks; no other step)",
    ],
    approval_mode="internal",
    role="action",
    side_effects=True,
    params_schema=CommunicationParams.model_json_schema(),
    output_schema={"type": "object", "properties": {
        "status": {"type": "string", "description": "ok | failed | rejected"},
        "delivery": {"type": "string", "description": "sent | logged (console)"},
        "message_id": {"type": "string"},
        "to": {"type": "array", "description": "recipients"},
        "subject": {"type": "string"},
    }},
    owner="team-comms",
)
