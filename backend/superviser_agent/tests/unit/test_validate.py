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
