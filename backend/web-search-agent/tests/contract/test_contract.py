from web_search_agent.card import CARD
from web_search_agent.graph import graph

from utils import AgentTask
from utils.testing import assert_agent_contract


def test_web_search_agent_contract():
    result = assert_agent_contract(CARD, graph, AgentTask(task_id="s1", objective="What is the price of iPhone 16?"))
    assert result["status"] == "ok"
    assert result["sources"]
