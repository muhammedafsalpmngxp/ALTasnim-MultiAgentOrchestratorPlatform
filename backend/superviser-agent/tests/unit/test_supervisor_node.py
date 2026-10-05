"""The supervisor node's code around the LLM: which results a revised plan reuses, and the chat history."""

from langchain_core.messages import AIMessage, HumanMessage
from orchestrator_agent.nodes.supervisor import history, reusable

from utils import Plan, Step


def steps(*items: Step) -> Plan:
    return Plan(goal="g", steps=list(items))


OK = {"status": "ok"}


def test_a_revised_plan_reuses_unchanged_finished_steps_only():
    old = steps(Step(id="s1", agent="rag", objective="find", params={"question": "q"}),
                Step(id="s2", agent="web_search", objective="Oman price"),
                Step(id="s3", agent="verifier", objective="check", depends_on=["s1", "s2"]))
    new = steps(Step(id="s1", agent="rag", objective="find", params={"question": "q"}),       # unchanged: kept
                Step(id="s2", agent="web_search", objective="Oman price in OMR"),            # changed: runs again
                Step(id="s3", agent="verifier", objective="check", depends_on=["s1", "s2"]))  # its input changed
    results = {"s1": OK, "s2": OK, "s3": OK}
    assert reusable(new, old, results) == {"s1"}


def test_failed_steps_and_steps_of_a_new_plan_are_not_reused():
    old = steps(Step(id="s1", agent="rag", objective="find"))
    assert reusable(old, old, {"s1": {"status": "failed"}}) == set()
    assert reusable(old, None, {"s1": OK}) == set()


def test_history_is_the_chat_before_this_request():
    state = {"request": "and in UAE?", "messages": [
        HumanMessage("iPhone price in Oman?"), AIMessage("OMR 349"), HumanMessage("and in UAE?")]}
    assert history(state) == [("user", "iPhone price in Oman?"), ("assistant", "OMR 349")]
    assert history({"request": "hi", "messages": [HumanMessage("hi")]}) == []
