from web_search_agent.card import CARD, WebSearchParams
from web_search_agent.graph import graph

from utils import AgentTask
from utils.testing import assert_agent_contract


def test_web_search_agent_contract(offline):
    result = assert_agent_contract(CARD, graph, AgentTask(task_id="s1", objective="What is the price of iPhone 16?"))
    assert result["status"] == "ok"
    assert result["sources"]
    # Offline default: sample data, never downloads pages
    assert "[SAMPLE DATA]" in result["summary"]
    assert offline["fetch_calls"] == []


def test_result_satisfies_the_verifier_checks():
    """What verifier_agent.nodes.checks looks at in each input from a web_search step."""
    result = assert_agent_contract(CARD, graph, AgentTask(task_id="s1", objective="iPhone price"))
    assert result["status"] == "ok" and result["summary"].strip()
    assert result["findings"]
    assert all(isinstance(u, str) and u.startswith(("http://", "https://")) for u in result["sources"])
    assert result["sources"] == [f["url"] for f in result["findings"]]


def test_result_is_only_the_question_and_top_3_contents():
    result = assert_agent_contract(CARD, graph, AgentTask(task_id="s1", objective="iPhone price"))
    assert set(result) == set(CARD.output_schema["properties"]) == {"status", "summary", "question", "findings",
                                                                     "sources"}
    assert result["question"] == "iPhone price" and len(result["findings"]) == 3


def test_supervisor_params_are_valid_against_the_card():
    # What the rule planner sends for "Compare iPhone price in Oman and UAE"
    WebSearchParams.model_validate({"query": "iPhone price", "region": "Oman"})
    assert set(CARD.params_schema["properties"]) == {"query", "region", "freshness", "include_domains",
                                                    "exclude_domains"}
