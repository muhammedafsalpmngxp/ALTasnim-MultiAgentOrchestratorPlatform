from jsonschema import Draft202012Validator
from verifier_agent.card import CARD
from verifier_agent.graph import graph

from utils import AgentTask
from utils.testing import assert_agent_contract


def test_verifier_agent_contract(monkeypatch):
    monkeypatch.delenv("VERIFIER_LLM_MODEL", raising=False)  # rule checks only: no network
    task = AgentTask(task_id="v1", objective="Verify", params={"request": "q", "answer_step": "s1"},
                     inputs={"s1": {"status": "ok", "answer": "an answer"}})
    result = assert_agent_contract(CARD, graph, task)
    assert result["passed"] is True
    assert {"status", "summary", "passed", "issues", "warnings", "missing", "rejected_steps", "fix"} <= set(result)


def test_the_card_params_accept_what_the_platform_sends():
    params = {"request": "Who issues the pegging sheet?", "answer_step": "s2"}
    assert list(Draft202012Validator(CARD.params_schema).iter_errors(params)) == []
    assert CARD.role == "verifier"
