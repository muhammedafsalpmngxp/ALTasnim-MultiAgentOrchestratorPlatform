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


RAG_OUTPUT = {"question": "What is the notice period?",
              "chunks": [{"document_name": "contract.pdf", "content": "The notice period is 30 days."}]}


class _FakeJudge:
    """Stands in for the LLM: ``model.with_structured_output(Judgement).invoke(prompt)``."""

    def __init__(self, verified: bool):
        self.verified, self.prompts = verified, []

    def with_structured_output(self, schema):
        self.schema = schema
        return self

    def invoke(self, prompt):
        self.prompts.append(prompt)
        return self.schema(verified=self.verified, reason="judged by fake")


def _judge(monkeypatch, verified: bool) -> _FakeJudge:
    fake = _FakeJudge(verified)
    monkeypatch.setattr("verifier_agent.nodes.checks.judge_model", lambda: fake)
    return fake


def test_rag_chunks_without_summary_are_content():
    result = _verify({"rag": RAG_OUTPUT})
    assert result["status"] == "ok"
    assert any("answer check skipped" in w for w in result["warnings"])  # no LLM in tests


def test_llm_verified_passes(monkeypatch):
    fake = _judge(monkeypatch, verified=True)
    result = _verify({"rag": RAG_OUTPUT})
    assert result["passed"] is True
    assert result["judgements"]["rag"] == {"verified": True, "reason": "judged by fake"}
    assert "What is the notice period?" in fake.prompts[0] and "30 days" in fake.prompts[0]


def test_llm_not_verified_fails(monkeypatch):
    _judge(monkeypatch, verified=False)
    result = _verify({"rag": RAG_OUTPUT})
    assert result["status"] == "failed"
    assert any("does not answer the question" in i for i in result["issues"])
