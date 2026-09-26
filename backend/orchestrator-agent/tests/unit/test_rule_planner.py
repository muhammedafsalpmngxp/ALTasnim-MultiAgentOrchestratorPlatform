from communication_agent.card import CARD as COMM
from orchestrator_agent.planning.rule_planner import RulePlanner
from verifier_agent.card import CARD as VERIFIER
from web_search_agent.card import CARD as SEARCH

CARDS = {"web_search": SEARCH, "communication": COMM, "verifier": VERIFIER}


def decide(request, clarifications=()):
    return RulePlanner().decide(request, list(clarifications), CARDS, {}, [])


def test_price_question_uses_web_search_only():
    d = decide("What is the price of iPhone?")
    assert d.action == "plan"
    assert [s.agent for s in d.plan.steps] == ["web_search"]


def test_price_then_email_is_sequential():
    d = decide("check the price of iphone then share the mail to rijin@gmail.com")
    s1, s2 = d.plan.steps
    assert (s1.agent, s2.agent) == ("web_search", "communication")
    assert s2.depends_on == ["s1"]
    assert s2.params["to"] == ["rijin@gmail.com"]
    assert "rijin" not in s1.objective


def test_compare_runs_two_searches_in_parallel_then_email():
    d = decide("Compare iPhone price in Oman and UAE and email it to rijin@gmail.com")
    s1, s2, s3 = d.plan.steps
    assert (s1.params["region"], s2.params["region"]) == ("Oman", "UAE")
    assert s1.depends_on == [] and s2.depends_on == []
    assert s3.agent == "communication" and s3.depends_on == ["s1", "s2"]


def test_email_without_recipient_asks_for_clarification():
    assert decide("check the iPhone price and email it").action == "clarify"
    d = decide("check the iPhone price and email it", ["rijin@gmail.com"])
    assert d.action == "plan" and d.plan.steps[-1].params["to"] == ["rijin@gmail.com"]


def test_greeting_is_answered_directly():
    assert decide("hello").action == "answer"
