from communication_agent.card import CARD
from communication_agent.graph import graph

from utils import AgentTask
from utils.testing import assert_agent_contract


def test_communication_agent_contract():
    task = AgentTask(task_id="s2", objective="Email the price", params={"to": ["rijin@gmail.com"]},
                     inputs={"s1": {"status": "ok", "summary": "iPhone 16 costs X"}})
    result = assert_agent_contract(CARD, graph, task)
    assert result["delivery"] == "sent"
