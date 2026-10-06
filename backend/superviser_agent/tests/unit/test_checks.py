"""The platform's check added to a plan (planning/checks.py): by role and policy, never by agent name."""

from communication_agent.card import CARD as COMM
from orchestrator_agent.nodes.progress import rejected_by
from orchestrator_agent.planning.checks import add_checks
from orchestrator_agent.planning.validate import check_plan
from orchestrator_agent.settings import Policies
from synthesizer_agent.card import CARD as SYNTH_CARD
from verifier_agent.card import CARD as VERIFIER
from web_search_agent.card import CARD as SEARCH

from utils import AgentCard, Plan, Step

SYNTH = AgentCard.model_validate(SYNTH_CARD)
CHECKER = VERIFIER.model_copy(update={"name": "quality_gate"})  # any name: found by its role
CARDS = {"web_search": SEARCH, "synthesizer": SYNTH, "quality_gate": CHECKER, "communication": COMM}
REQUEST = "Compare the iPhone 16 price in Oman and UAE"


def make(*steps: dict) -> Plan:
    return Plan(goal="Compare prices", success_criteria=["Oman price", "UAE price"], steps=[Step(**s) for s in steps])


def search(sid, region):
    return {"id": sid, "agent": "web_search", "objective": f"Find the price in {region}",
            "params": {"query": "iPhone 16 price", "region": region}}


def answer(sid="s3", deps=("s1", "s2"), **params):
    return {"id": sid, "agent": "synthesizer", "objective": "Compare", "params": {"question": REQUEST, **params},
            "depends_on": list(deps)}


def email(sid="m1", deps=("s1",), **params):
    return {"id": sid, "agent": "communication", "objective": "Email it",
            "params": {"channel": "email", "to": ["a@b.com"], **params}, "depends_on": list(deps)}


def checks(plan: Plan) -> dict[str, Step]:
    return {s.id: s for s in plan.steps if s.added_by == "policy"}


def test_the_final_answer_is_checked_with_the_question_and_the_answer_only():
    plan = add_checks(make(search("s1", "Oman"), search("s2", "UAE"), answer()), CARDS, Policies(), REQUEST)
    check = checks(plan)["check_s3"]
    assert check.agent == "quality_gate" and check.depends_on == ["s3"]  # not the search steps
    assert check.params == {"request": REQUEST, "answer_step": "s3"}
    assert check_plan(plan, CARDS) == []  # the check's params fit the verifier's card


def test_a_summary_of_the_users_text_is_checked_too():
    plan = add_checks(make(answer("s1", deps=(), content="Rig 12 moves on 3 May.")), CARDS, Policies(), "Summarise")
    assert checks(plan)["check_s1"].depends_on == ["s1"]


def test_an_email_of_a_checked_answer_waits_for_the_check():
    plan = add_checks(make(search("s1", "Oman"), search("s2", "UAE"), answer(), email(deps=("s3",))),
                      CARDS, Policies(), REQUEST)
    assert set(checks(plan)) == {"check_s3"}
    assert next(s for s in plan.steps if s.id == "m1").after == ["check_s3"]


def test_no_check_without_a_final_answer():
    for plan in (make(search("s1", "Oman"), email()), make(email(deps=(), body="Hello"))):
        assert add_checks(plan, CARDS, Policies(), REQUEST) == plan


def test_no_check_without_a_verifier_or_with_the_policy_off():
    plan = make(search("s1", "Oman"), answer(deps=("s1",)))
    no_verifier = {k: v for k, v in CARDS.items() if k != "quality_gate"}
    assert add_checks(plan, no_verifier, Policies(), REQUEST) == plan
    assert add_checks(plan, CARDS, Policies(verify_final=False), REQUEST) == plan


def test_a_plan_that_already_checks_the_answer_gets_no_second_check():
    plan = make(search("s1", "Oman"), answer(deps=("s1",)),
                {"id": "v1", "agent": "quality_gate", "objective": "check", "depends_on": ["s3"]})
    assert add_checks(plan, CARDS, Policies(), REQUEST) == plan


def test_check_ids_never_clash():
    plan = make(search("check_s3", "Oman"), answer(deps=("check_s3",)))
    assert "check_s3_2" in checks(add_checks(plan, CARDS, Policies(), REQUEST))


def test_a_failed_check_rejects_only_the_steps_it_names():
    assert rejected_by({"rejected_steps": ["s3", "zz"]}, ["s3", "s1", "s2"]) == ["s3"]
    assert rejected_by({"rejected_steps": []}, ["s3", "s1"]) == []  # the check could not run: nobody blamed
    assert rejected_by({"summary": "failed"}, ["s3", "s1"]) == ["s3", "s1"]  # a verifier that names none
