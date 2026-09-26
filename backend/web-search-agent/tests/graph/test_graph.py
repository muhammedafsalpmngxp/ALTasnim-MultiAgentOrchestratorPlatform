from web_search_agent.graph import graph
from web_search_agent.nodes.plan_queries import rule_based_queries

from utils import AgentTask
from utils.testing import run_agent_graph


def test_price_question_runs_parallel_queries():
    assert len(rule_based_queries("iPhone 16 price")) == 2


def test_region_is_added_to_query():
    task = AgentTask(task_id="s1", objective="Find iPhone price", params={"query": "iPhone price", "region": "Oman"})
    result = run_agent_graph(graph, task)
    assert result["status"] == "ok"
    assert all("Oman" in f["query"] for f in result["findings"])


def test_max_sources_is_respected():
    task = AgentTask(task_id="s1", objective="iPhone price", params={"max_sources": 2})
    result = run_agent_graph(graph, task)
    assert len(result["findings"]) == 2
