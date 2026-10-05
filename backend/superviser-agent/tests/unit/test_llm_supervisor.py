"""The supervisor's thinking (planning/llm_supervisor.py) with a fake LLM: what it reads, what it may answer,
and how it fixes a plan that cannot run. No network."""

import re

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from orchestrator_agent import llm
from orchestrator_agent.planning.llm_supervisor import (
    PLAN_PROMPT,
    REVIEW_PROMPT,
    LLMSupervisor,
    PlanNotRunnable,
    SupervisorContext,
    decision_schema,
    digest,
)
from pydantic import ValidationError
from verifier_agent.card import CARD as VERIFIER
from web_search_agent.card import CARD as SEARCH

from utils import AgentCard, Plan, Step

QUESTION = {"type": "object", "properties": {"question": {"type": "string", "description": "the user's question"}},
            "required": ["question"]}
RAG = AgentCard(name="rag", version="1.0.0", description="Finds passages in the user's documents",
                when_to_use="questions about the user's documents", when_not_to_use="the web", role="source",
                params_schema=QUESTION, output_schema={"properties": {"chunks": {"description": "passages"}}})
SYNTH = AgentCard(name="synthesizer", version="1.0.0", description="Writes the final answer", role="final_answer",
                  when_to_use="last step", when_not_to_use="finding facts", params_schema=QUESTION)
CARDS = {"rag": RAG, "web_search": SEARCH, "verifier": VERIFIER, "synthesizer": SYNTH}

GOOD_PLAN = {
    "understanding": "The current iPhone 16 price in Oman", "needs": ["price", "check", "answer"],
    "reasoning": "web_search finds it, the verifier checks it, the synthesizer answers", "action": "plan",
    "plan": {"goal": "iPhone 16 price in Oman", "success_criteria": ["a price with a source"], "steps": [
        {"id": "s1", "agent": "web_search", "objective": "Find the iPhone 16 price in Oman",
         "params": {"query": "iPhone 16 price", "region": "Oman"}},
        {"id": "s2", "agent": "verifier", "objective": "Check the price has a source", "depends_on": ["s1"]},
        {"id": "s3", "agent": "synthesizer", "objective": "Answer", "params": {"question": "iPhone price?"},
         "depends_on": ["s1", "s2"]},
    ]},
}


class FakeModel:
    """Returns the given decisions in order, validated by the schema the supervisor built (like the real one)."""

    def __init__(self, *outputs):
        self.outputs = list(outputs)
        self.calls: list[list] = []
        self.schema = self.method = None

    def with_structured_output(self, schema, method=None, include_raw=False):
        self.schema, self.method = schema, method
        model = self

        class Runner:
            def invoke(self, messages):
                model.calls.append(list(messages))
                raw = AIMessage("", usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120})
                try:
                    return {"raw": raw, "parsed": schema.model_validate(model.outputs.pop(0)), "parsing_error": None}
                except ValidationError as exc:
                    return {"raw": raw, "parsed": None, "parsing_error": exc}

        return Runner()


def ctx(**kw):
    return SupervisorContext(**{"mode": "plan", "request": "What is the iPhone 16 price in Oman?", "cards": CARDS,
                                **kw})


def test_plan_mode_reads_the_agent_cards_and_returns_the_plan():
    model, c = FakeModel(GOOD_PLAN), ctx()
    decision = LLMSupervisor(model).decide(c)

    assert decision.action == "plan" and decision.understanding.startswith("The current")
    assert [(s.id, s.agent, s.depends_on) for s in decision.plan.steps] == [
        ("s1", "web_search", []), ("s2", "verifier", ["s1"]), ("s3", "synthesizer", ["s1", "s2"])]
    assert decision.plan.steps[0].params == {"query": "iPhone 16 price", "region": "Oman"}
    assert decision.plan.success_criteria == ["a price with a source"]
    system, human = model.calls[0]
    assert isinstance(system, SystemMessage) and system.content == PLAN_PROMPT
    assert isinstance(human, HumanMessage)
    for text in ("USER REQUEST\nWhat is the iPhone 16 price in Oman?", "### web_search", "- role: source",
                 "- role: final_answer", "params schema:", "returns: chunks (passages)", "TODAY:"):
        assert text in human.content
    assert model.method == "function_calling"
    assert c.usage == {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}


def test_the_prompts_name_no_agent():
    """Everything about an agent comes from its card, so a new agent needs no prompt change."""
    for name in ("rag", "web_search", "synthesizer", "communication"):
        for prompt in (PLAN_PROMPT, REVIEW_PROMPT):
            assert not re.search(rf"\b{name}\b", prompt)


def test_the_llm_can_only_choose_an_available_agent():
    schema = decision_schema(["verifier", "web_search"])
    bad = {**GOOD_PLAN, "plan": {"goal": "g", "steps": [{"id": "s1", "agent": "rag", "objective": "x"}]}}
    with pytest.raises(ValidationError):
        schema.model_validate(bad)


def test_a_plan_that_cannot_run_goes_back_to_the_llm_with_the_errors():
    broken = {**GOOD_PLAN, "plan": {"goal": "g", "steps": [
        {"id": "s1", "agent": "web_search", "objective": "x", "depends_on": ["s9"]}]}}
    model = FakeModel(broken, GOOD_PLAN)
    decision = LLMSupervisor(model).decide(ctx())

    assert decision.action == "plan" and len(model.calls) == 2
    repair = model.calls[1][-1].content
    assert "Your decision cannot be used" in repair and "depends on unknown step 's9'" in repair


def test_an_unknown_agent_is_also_repaired_and_gives_up_after_the_repairs():
    unknown = {**GOOD_PLAN, "plan": {"goal": "g", "steps": [{"id": "s1", "agent": "sql", "objective": "x"}]}}
    model = FakeModel(unknown, unknown)
    with pytest.raises(PlanNotRunnable) as err:
        LLMSupervisor(model).decide(ctx(max_repairs=1))
    assert "could not be read" in err.value.errors[0] and len(model.calls) == 2


def test_review_mode_shows_the_plan_results_failures_and_replans_left():
    plan = Plan(goal="Who issues the pegging sheet?", success_criteria=["the issuer"], steps=[
        Step(id="s1", agent="rag", objective="find", params={"question": "q"}),
        Step(id="s2", agent="verifier", objective="check", depends_on=["s1"])])
    results = {
        "s1": {"step_id": "s1", "agent": "rag", "status": "failed", "error": "failed verification (s2): off topic",
               "output": {"chunks": [{"document_name": "rules.pdf", "content": "Unrelated clause"}]}},
        "s2": {"step_id": "s2", "agent": "verifier", "status": "failed", "error": "Verification failed",
               "output": {"summary": "Verification failed", "issues": ["s1: off topic"]}},
    }
    model = FakeModel({"understanding": "u", "reasoning": "r", "action": "answer", "answer": "Sorry"})
    LLMSupervisor(model).decide(ctx(mode="review", plan=plan, results=results, review_reason="failed",
                                    feedback=["step s1 (rag) failed verification: off topic"], replans_left=0))

    system, human = model.calls[0]
    assert system.content == REVIEW_PROMPT
    for text in ("WHY YOU ARE REVIEWING", "step s1 (rag) failed verification", "s1 · agent rag · status: failed",
                 "[rules.pdf] Unrelated clause", "issues: s1: off topic", "success criteria: the issuer",
                 "REPLANS LEFT: 0 (you cannot make a new plan"):
        assert text in human.content


def test_digest_reads_passages_without_a_summary_and_is_capped():
    out = {"status": "ok", "chunks": [{"document_name": "rules.pdf", "content": "PDO issues the sheet"}]}
    assert digest(out) == "[rules.pdf] PDO issues the sheet"
    assert digest({"summary": "x" * 5000}, limit=100).endswith("…")
    assert digest({"summary": "Answer", "sources": ["https://a", "https://b"]}) == "Answer\nsources: https://a, https://b"


def test_model_from_env_bare_name_means_openai_and_no_temperature_unless_set(monkeypatch):
    seen = {}
    monkeypatch.setattr("langchain.chat_models.init_chat_model", lambda name, **kw: seen.update(name=name, **kw))
    monkeypatch.setenv("SUPERVISOR_LLM_MODEL", " gpt-test ")
    monkeypatch.delenv("SUPERVISOR_LLM_TEMPERATURE", raising=False)
    llm.supervisor_model.cache_clear()
    try:
        llm.supervisor_model()
        assert seen["name"] == "openai:gpt-test" and "temperature" not in seen
        monkeypatch.setenv("SUPERVISOR_LLM_TEMPERATURE", "0")
        llm.supervisor_model.cache_clear()
        llm.supervisor_model()
        assert seen["temperature"] == 0.0
    finally:
        llm.supervisor_model.cache_clear()


def test_no_model_configured_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("SUPERVISOR_LLM_MODEL", raising=False)
    llm.supervisor_model.cache_clear()
    with pytest.raises(llm.SupervisorLLMUnavailable, match="set SUPERVISOR_LLM_MODEL"):
        LLMSupervisor().decide(ctx())
    llm.supervisor_model.cache_clear()
