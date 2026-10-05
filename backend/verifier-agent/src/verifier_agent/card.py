from __future__ import annotations

from utils import AgentCard

CARD = AgentCard(
    name="verifier",
    version="0.1.0",
    description="Checks the outputs of earlier steps for missing evidence, failures and incompleteness.",
    when_to_use="Before results are shown to a human approver or the user. Usually added automatically by policy.",
    when_not_to_use="Producing new information or sending messages.",
    examples=[
        "Verify the iPhone prices found are sourced",
        "Check the comparison covers both countries",
    ],
    approval_mode="none",
    role="verifier",
    params_schema={"type": "object", "properties": {}},
    output_schema={
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "passed": {"type": "boolean"},
            "issues": {"type": "array", "items": {"type": "string"}},
            "warnings": {"type": "array", "items": {"type": "string"}},
        },
    },
    owner="team-quality",
)
