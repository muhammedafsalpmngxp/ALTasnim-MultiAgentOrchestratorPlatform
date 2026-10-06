"""Can the plan run? (planning/validate.py) The errors go back to the supervisor's LLM."""

from orchestrator_agent.planning.validate import check_plan
from verifier_agent.card import CARD as VERIFIER
from web_search_agent.card import CARD as SEARCH

from utils import Plan, Step

CARDS = {"web_search": SEARCH, "verifier": VERIFIER}


def plan(*steps: Step) -> Plan:
    return Plan(goal="g", steps=list(steps))


def test_a_plan_with_known_agents_and_dependencies_can_run():
    p = plan(Step(id="s1", agent="web_search", objective="Oman price"),
             Step(id="s2", agent="web_search", objective="UAE price"),
             Step(id="s3", agent="verifier", objective="check", depends_on=["s1", "s2"]))
    assert check_plan(p, CARDS) == []


def test_unknown_agent_is_rejected_with_the_available_ones():
    errors = check_plan(plan(Step(id="s1", agent="nope", objective="x")), CARDS)
    assert errors == ["step s1: unknown or unavailable agent 'nope'; available: ['verifier', 'web_search']"]


def test_unknown_dependency_duplicate_ids_and_cycles_are_rejected():
    assert any("unknown step 's9'" in e for e in check_plan(
        plan(Step(id="s1", agent="web_search", objective="a", depends_on=["s9"])), CARDS))
    assert any("duplicate step ids" in e for e in check_plan(
        plan(Step(id="s1", agent="web_search", objective="a"), Step(id="s1", agent="verifier", objective="b")), CARDS))
    cycle = plan(Step(id="s1", agent="web_search", objective="a", depends_on=["s2"]),
                 Step(id="s2", agent="web_search", objective="b", depends_on=["s1"]))
    assert any("cycle" in e for e in check_plan(cycle, CARDS))


def test_an_empty_plan_cannot_run():
    assert check_plan(Plan(goal="g", steps=[]), CARDS) == ["the plan has no steps"]


def test_a_verifier_or_final_answer_without_inputs_is_sent_back_to_the_llm():
    from utils import AgentCard

    synth = AgentCard(name="synthesizer", version="1.0.0", description="d", when_to_use="w", when_not_to_use="n",
                      role="final_answer")
    cards = {**CARDS, "synthesizer": synth}
    errors = check_plan(plan(Step(id="s1", agent="verifier", objective="check the email text")), cards)
    assert any("a verifier checks the outputs of earlier steps" in e for e in errors)
    errors = check_plan(plan(Step(id="s1", agent="synthesizer", objective="draft the email")), cards)
    assert any("a final answer is written from the outputs of earlier steps" in e for e in errors)


def test_params_follow_the_agents_schema():
    from communication_agent.card import CARD as COMM

    cards = {**CARDS, "communication": COMM}
    errors = check_plan(plan(Step(id="s1", agent="communication", objective="mail", params={"subject": "x"})), cards)
    assert any("'to' is a required property" in e for e in errors)
    ok = Step(id="s1", agent="communication", objective="mail", params={"to": ["a@b.com"], "body": "Hello"})
    assert check_plan(plan(ok), cards) == []  # the user's text alone: one step is a valid plan
