from verifier_agent.card import CARD
from verifier_agent.graph import graph

from utils import AgentTask
from utils.testing import assert_agent_contract


def test_verifier_agent_contract():
    task = AgentTask(task_id="v1", objective="Verify", inputs={
        "s1": {"status": "ok", "summary": "found", "findings": [{"x": 1}], "sources": ["https://apple.com"]}})
    assert assert_agent_contract(CARD, graph, task)["passed"] is True
