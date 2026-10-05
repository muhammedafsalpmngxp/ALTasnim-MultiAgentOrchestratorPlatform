"""Contracts shared by the orchestrator and every agent deployment.

Rules:
- Graph state stores plain dicts (``model.model_dump()``), never model instances.
  Checkpoints stay JSON-friendly and readable by the Angular UI through the
  LangGraph SDK. Nodes parse them back with ``Model.model_validate(...)``.
- Every agent graph accepts ``AgentInput`` and returns ``AgentOutput``
  (``StateGraph(..., input_schema=AgentInput, output_schema=AgentOutput)``).
"""

from __future__ import annotations

import uuid
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- #
# Agent contract (orchestrator  <->  agent deployment)
# --------------------------------------------------------------------------- #


class AgentTask(BaseModel):
    """What the orchestrator sends to an agent for one plan step."""

    task_id: str
    objective: str
    params: dict[str, Any] = Field(default_factory=dict)
    # Outputs of the steps this step depends on, keyed by step id.
    inputs: dict[str, Any] = Field(default_factory=dict)


class AgentInput(TypedDict):
    """Input schema of EVERY agent graph."""

    task: dict  # AgentTask.model_dump()


class AgentOutput(TypedDict, total=False):
    """Output schema of EVERY agent graph.

    ``result`` must contain at least ``status`` ("ok" | "failed" | "rejected")
    and ``summary`` (one human-readable line). Everything else is agent-specific
    and described by the agent's ``AgentCard.output_schema``.
    """

    result: dict


ApprovalMode = Literal["none", "internal", "gate"]
"""
none     - never needs a human.
internal - the agent calls ``interrupt()`` itself (e.g. edit the email before
           sending). The orchestrator bridges the interrupt to its own inbox.
gate     - the orchestrator inserts a ``hitl`` step before this agent runs.
"""

AgentRole = Literal["source", "transform", "final_answer", "verifier", "action"]
"""
What kind of agent it is. The supervisor plans and answers by role, never by agent name, so a new agent with a
role fits the flow without changes to the supervisor.

source       - finds facts (documents, the web, a database), e.g. rag, web_search.
transform    - changes the outputs of earlier steps (translate, convert, extract).
final_answer - writes the ONE final answer from the earlier steps; its answer is the reply, e.g. synthesizer.
verifier     - checks the outputs of earlier steps, e.g. verifier.
action       - does something outside the platform (email, ticket, publish), e.g. communication.
"""


class AgentCard(BaseModel):
    """Self-description of an agent. The supervisor plans from these cards.

    Served by every agent at ``GET /card`` (LangGraph ``http.app`` custom route).
    Clear ``when_to_use`` / ``when_not_to_use`` / ``examples`` matter more for
    plan quality than a clever supervisor prompt.
    """

    name: str
    version: str
    description: str
    when_to_use: str
    when_not_to_use: str
    examples: list[str] = Field(default_factory=list)
    approval_mode: ApprovalMode = "none"
    role: AgentRole | None = None
    # Sends or changes something outside the platform (email, ticket, publish).
    side_effects: bool = False
    params_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})
    output_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})
    owner: str = "unassigned"


class AgentResult(BaseModel):
    """What the orchestrator records for each finished (or failed) step."""

    step_id: str
    agent: str
    status: Literal["ok", "failed", "rejected", "revise", "pending"]
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


# --------------------------------------------------------------------------- #
# Plan contract (supervisor -> plan_guard -> progress)
# --------------------------------------------------------------------------- #


class Step(BaseModel):
    id: str = Field(description="Short unique id, e.g. 's1'.")
    agent: str = Field(description="Agent name from the registry, or 'hitl' for a human approval step.")
    kind: Literal["agent", "hitl"] = "agent"
    objective: str = Field(description="What this step must achieve, in one sentence.")
    params: dict[str, Any] = Field(default_factory=dict, description="Structured inputs for the agent.")
    depends_on: list[str] = Field(
        default_factory=list,
        description="Step ids that must finish first. Their outputs are passed to this step as inputs.",
    )
    after: list[str] = Field(
        default_factory=list,
        description="Ordering-only dependencies added by policy (verifier / approval). Outputs are NOT passed.",
    )
    added_by: Literal["supervisor", "policy"] = "supervisor"
    expected_output: str = Field("", description="What a good result of this step looks like.")


class Plan(BaseModel):
    plan_id: str = Field(default_factory=lambda: f"p_{uuid.uuid4().hex[:8]}")
    version: int = 1
    goal: str
    reasoning: str = ""
    # What "done" means; the supervisor checks the results against it when it reviews the run.
    success_criteria: list[str] = Field(default_factory=list)
    steps: list[Step]


class SupervisorDecision(BaseModel):
    """What the supervisor decided (from its LLM's structured output).

    plan mode (a new request):  answer | clarify | plan
    review mode (a step failed, a verifier rejected, or the run ended without a final answer):
                                finish | plan (revised) | clarify | answer
    """

    action: Literal["answer", "clarify", "plan", "finish"]
    understanding: str = ""  # the user's goal in one sentence
    needs: list[str] = Field(default_factory=list)  # what is needed to satisfy it
    reasoning: str = ""  # which agents, why, in which order
    answer: str | None = None
    question: str | None = None
    plan: Plan | None = None


class StepStatus(BaseModel):
    """Live execution status of one step, shown in the Runs UI."""

    status: Literal["queued", "running", "waiting_approval", "done", "failed", "rejected", "skipped"]
    agent: str
    updated_at: str
    remote_thread: str | None = None
    detail: str | None = None
