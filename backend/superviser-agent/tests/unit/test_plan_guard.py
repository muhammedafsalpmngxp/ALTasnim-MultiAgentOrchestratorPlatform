from communication_agent.card import CARD as COMM
from orchestrator_agent.planning.policies import enforce_policies
from orchestrator_agent.planning.validate import validate_plan
from orchestrator_agent.settings import Policies
from verifier_agent.card import CARD as VERIFIER
from web_search_agent.card import CARD as SEARCH

from utils import AgentCard, Plan, Step

CARDS = {"web_search": SEARCH, "communication": COMM, "verifier": VERIFIER}
POLICIES = Policies()


def plan(*steps: Step) -> Plan:
    return Plan(goal="g", steps=list(steps))


def by_id(p: Plan) -> dict[str, Step]:
    return {s.id: s for s in p.steps}


# ---- validation -------------------------------------------------------- #

def test_unknown_agent_is_rejected():
    errors = validate_plan(plan(Step(id="s1", agent="nope", objective="x")), CARDS, POLICIES)
    assert any("unknown or unavailable agent" in e for e in errors)


def test_cycle_is_rejected():
    p = plan(Step(id="s1", agent="web_search", objective="a", depends_on=["s2"]),
             Step(id="s2", agent="web_search", objective="b", depends_on=["s1"]))
    assert any("cycle" in e for e in validate_plan(p, CARDS, POLICIES))


def test_params_are_checked_against_the_agent_schema():
    p = plan(Step(id="s1", agent="communication", objective="mail", params={"channel": "email"}))
    assert any("'to' is a required property" in e for e in validate_plan(p, CARDS, POLICIES))


def test_email_domain_allowlist():
    p = plan(Step(id="s1", agent="communication", objective="mail", params={"to": ["x@gmail.com"]}))
    errors = validate_plan(p, CARDS, Policies(allowed_email_domains=["altasnim.com"]))
    assert any("outside allowed domains" in e for e in errors)


# ---- policies ---------------------------------------------------------- #

def test_search_only_gets_final_verifier():
    steps = by_id(enforce_policies(plan(Step(id="s1", agent="web_search", objective="price")), CARDS, POLICIES))
    assert steps["v_final"].depends_on == ["s1"]


def test_verifier_runs_before_email_but_does_not_change_its_inputs():
    p = plan(Step(id="s1", agent="web_search", objective="price"),
             Step(id="s2", agent="communication", objective="mail", params={"to": ["a@b.com"]}, depends_on=["s1"]))
    steps = by_id(enforce_policies(p, CARDS, POLICIES))
    assert steps["v_s2"].depends_on == ["s1"]
    assert steps["s2"].depends_on == ["s1"]  # still gets the search output
    assert steps["s2"].after == ["v_s2"]  # but waits for verification
    assert "v_final" not in steps


def test_gate_agent_gets_hitl_step_and_approvals_are_serialized():
    gated = AgentCard(name="publisher", version="0.1.0", description="d", when_to_use="w", when_not_to_use="n",
                      examples=["a", "b"], approval_mode="gate")
    cards = {**CARDS, "publisher": gated}
    p = plan(Step(id="s1", agent="web_search", objective="price"),
             Step(id="s2", agent="communication", objective="mail", params={"to": ["a@b.com"]}, depends_on=["s1"]),
             Step(id="s3", agent="publisher", objective="publish", depends_on=["s1"]))
    steps = by_id(enforce_policies(p, cards, POLICIES))
    assert steps["g_s3"].kind == "hitl"
    assert "g_s3" in steps["s3"].after
    assert "s2" in steps["g_s3"].after  # second approval waits for the first
