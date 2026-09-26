from verifier_agent.graph import graph

from utils import AgentTask
from utils.testing import run_agent_graph


def _verify(inputs: dict) -> dict:
    return run_agent_graph(graph, AgentTask(task_id="v1", objective="Verify", inputs=inputs))


def test_fails_when_no_findings():
    result = _verify({"s1": {"status": "ok", "summary": "nothing", "findings": [], "sources": []}})
    assert result["status"] == "failed"
    assert any("no findings" in i for i in result["issues"])


def test_fails_when_nothing_to_verify():
    assert _verify({})["status"] == "failed"


def test_sample_data_is_a_warning_not_a_failure():
    result = _verify({"s1": {"status": "ok", "summary": "[SAMPLE DATA] x", "findings": [{"a": 1}],
                             "sources": ["https://example.com/a"]}})
    assert result["status"] == "ok"
    assert result["warnings"]
