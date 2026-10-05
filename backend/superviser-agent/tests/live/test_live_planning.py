"""The supervisor's real LLM plans the questions of evals/planning/dataset.jsonl (decisions only: no agent runs).

Costs one LLM call per question, so it runs only on request:

    RUN_LIVE=1 SUPERVISOR_LLM_MODEL=openai:<model> OPENAI_API_KEY=... pytest superviser-agent/tests/live

(in Docker: docker run --env-file .env -e RUN_LIVE=1 ...). Checks the action, the agents chosen, that the verifier
checks the steps that find the facts, that the final answer comes last, and which steps run in parallel.
"""

import json
import os
from collections import Counter
from pathlib import Path

import pytest
from orchestrator_agent.planning.llm_supervisor import LLMSupervisor, SupervisorContext
from orchestrator_agent.settings import load_agents_config
from synthesizer_agent.card import CARD as SYNTH_CARD
from verifier_agent.card import CARD as VERIFIER
from web_search_agent.card import CARD as SEARCH

from utils import AgentCard

pytestmark = pytest.mark.skipif(
    not (os.getenv("RUN_LIVE") and os.getenv("SUPERVISOR_LLM_MODEL")),
    reason="live LLM test: set RUN_LIVE=1 and SUPERVISOR_LLM_MODEL",
)

DATASET = Path(__file__).parents[2] / "evals" / "planning" / "dataset.jsonl"
CASES = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]

# The cards as the registry builds them (own card + config card fields). Rag's card is served by its API
# (Rag-agent/rag_agent/main.py, GET /card); the same text here so this test does not load its models.
_config = load_agents_config().agents
RAG = AgentCard.model_validate({
    "name": "rag", "version": "1.0.0",
    "description": "Finds the passages of the user's uploaded documents that answer a question (hybrid dense + "
                   "sparse search in Qdrant, then reranked).",
    "when_to_use": "The question is about the user's own uploaded documents (contracts, reports, project rules, "
                   "policies, manuals).",
    "when_not_to_use": "Public or current information on the web (prices, news, weather); sending messages.",
    "examples": ["What is the retention money in the contract?", "Who issues the pegging sheet?"],
    "params_schema": {"type": "object", "properties": {
        "question": {"type": "string", "description": "the user's question"},
        "top_k": {"type": "integer", "minimum": 1, "maximum": 50}}, "required": ["question"]},
    "output_schema": {"type": "object", "properties": {"status": {}, "summary": {}, "question": {}, "chunks": {}}},
    **(_config["rag"].card or {}),
})
SYNTH = AgentCard.model_validate({**SYNTH_CARD, **(_config["synthesizer"].card or {})})
CARDS = {"rag": RAG, "web_search": SEARCH, "verifier": VERIFIER, "synthesizer": SYNTH}
FACTS = {"source", "transform"}


@pytest.fixture(scope="module")
def supervisor():
    return LLMSupervisor()


@pytest.mark.parametrize("case", CASES, ids=[c["request"][:40] for c in CASES])
def test_the_supervisor_plans_the_question(case, supervisor):
    ctx = SupervisorContext(mode="plan", request=case["request"], cards=CARDS)
    decision = supervisor.decide(ctx)
    print(f"\n{case['request']}\n  understanding: {decision.understanding}\n  reasoning: {decision.reasoning}"
          f"\n  usage: {ctx.usage}")
    assert decision.action == case["expected_action"], decision.reasoning
    if decision.action != "plan":
        return

    steps = {s.id: s for s in decision.plan.steps}
    for s in steps.values():
        print(f"  {s.id} {s.agent} <- {s.depends_on}: {s.objective} {s.params}")
    assert Counter(s.agent for s in steps.values()) == Counter(case["expected_agents"])

    role = {s.id: CARDS[s.agent].role for s in steps.values()}
    facts = {sid for sid, r in role.items() if r in FACTS}
    verifiers = [s for s in steps.values() if role[s.id] == "verifier"]
    finals = [s for s in steps.values() if role[s.id] == "final_answer"]
    assert all(facts <= set(v.depends_on) for v in verifiers), "the verifier checks every step that finds facts"
    for f in finals:  # the final answer comes after the facts and their check
        assert {v.id for v in verifiers} <= set(f.depends_on) and facts & set(f.depends_on)
    if agent := case.get("expected_parallel"):
        same = [s for s in steps.values() if s.agent == agent]
        assert len(same) > 1 and all(not set(s.depends_on) & {o.id for o in same} for s in same), "parallel"
