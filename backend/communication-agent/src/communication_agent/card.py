from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from utils import AgentCard


class CommunicationParams(BaseModel):
    channel: Literal["email"] = "email"  # TODO(team-comms): add "teams"
    to: list[str] = Field(min_length=1, description="Recipient email addresses.")
    subject: str | None = Field(default=None, description="Subject line. Generated if missing.")


class EmailDraft(BaseModel):
    to: list[str]
    subject: str
    body: str


CARD = AgentCard(
    name="communication",
    version="0.1.0",
    description="Drafts a message from the results of earlier steps and sends it after a human approves it.",
    when_to_use="The user asks to email, mail, share, send or notify someone.",
    when_not_to_use=(
        "Finding information (use web_search or data agents). "
        "Replying to the user in chat (the orchestrator does that)."
    ),
    examples=[
        "Share the iPhone price by mail to rijin@gmail.com",
        "Email the comparison to the sales team",
    ],
    approval_mode="internal",
    role="action",
    side_effects=True,
    params_schema=CommunicationParams.model_json_schema(),
    output_schema={"type": "object", "properties": {"status": {"type": "string"}, "message_id": {"type": "string"}}},
    owner="team-comms",
)
