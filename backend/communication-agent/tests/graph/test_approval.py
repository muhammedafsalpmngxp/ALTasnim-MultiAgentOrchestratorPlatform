import uuid

from communication_agent.graph import build_graph
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from utils import AgentTask

TASK = AgentTask(task_id="s2", objective="Email the iPhone price", params={"to": ["rijin@gmail.com"]},
                 inputs={"s1": {"status": "ok", "summary": "iPhone 16 costs X"}})


def _start():
    graph = build_graph().copy(update={"checkpointer": InMemorySaver()})
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    out = graph.invoke({"task": TASK.model_dump()}, config)
    return graph, config, out


def test_pauses_for_approval_with_draft():
    _, _, out = _start()
    request = out["__interrupt__"][0].value
    assert request["kind"] == "email_approval"
    assert request["draft"]["to"] == ["rijin@gmail.com"]
    assert "iPhone 16 costs X" in request["draft"]["body"]


def test_reject_does_not_send(monkeypatch):
    sent = []
    monkeypatch.setattr("communication_agent.nodes.send.send_email", lambda d: sent.append(d) or "id")
    graph, config, _ = _start()
    out = graph.invoke(Command(resume={"action": "reject", "reason": "wrong recipient"}), config)
    assert out["result"]["status"] == "rejected"
    assert sent == []


def test_edit_changes_what_is_sent(monkeypatch):
    sent = []
    monkeypatch.setattr("communication_agent.nodes.send.send_email", lambda d: sent.append(d) or "id")
    graph, config, _ = _start()
    out = graph.invoke(Command(resume={"action": "edit", "edited": {"subject": "Prices"}}), config)
    assert out["result"]["status"] == "ok"
    assert len(sent) == 1 and sent[0].subject == "Prices"
