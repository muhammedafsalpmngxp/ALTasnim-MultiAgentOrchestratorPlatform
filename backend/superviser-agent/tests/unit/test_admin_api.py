"""The admin view of every agent: status, port, machine, card; re-check, pause / resume, planning text; policies."""

import pytest
from fastapi.testclient import TestClient
from orchestrator_agent import api
from orchestrator_agent.clients import LocalAgentClient, RemoteAgentClient
from orchestrator_agent.deps import Deps
from orchestrator_agent.planning.rule_planner import RulePlanner
from orchestrator_agent.registry import AgentEntry, AgentRegistry, overrides
from orchestrator_agent.settings import Policies
from verifier_agent.card import CARD as VERIFIER
from web_search_agent.card import CARD as SEARCH

from utils import AgentCard
from utils.testing import build_stub_agent


@pytest.fixture
def client(monkeypatch):
    searches = []

    def locate(refresh):  # rag: no machine on the network serves it
        searches.append(refresh)
        return None

    def local(name, card):
        return AgentEntry(name, LocalAgentClient(build_stub_agent(name)), card, fetched_at=float("inf"))

    registry = AgentRegistry({
        "web_search": local("web_search", SEARCH),
        "verifier": local("verifier", VERIFIER),
        "rag": AgentEntry("rag", RemoteAgentClient(locate, "rag"), locate=locate),
    })
    deps = Deps(registry=registry, planner=RulePlanner(), policies=Policies())
    monkeypatch.setattr(api, "default_deps", lambda: deps)
    test_client = TestClient(api.app)
    test_client.searches = searches
    return test_client


def test_admin_lists_every_configured_agent_with_port_graph_and_status(client):
    body = client.get("/platform/admin/agents").json()
    assert body["supervisor"] == {"port": 8100, "graph_id": "orchestrator"}
    rows = {r["name"]: r for r in body["agents"]}
    assert set(rows) == {"web_search", "rag", "verifier", "synthesizer", "communication"}  # config/agents.dev.yaml
    assert (rows["rag"]["port"], rows["rag"]["graph_id"], rows["rag"]["status"]) == (8000, "rag", "not_found")
    assert "no machine on the network serves it" in rows["rag"]["error"]
    assert rows["web_search"]["status"] == "in_process" and rows["web_search"]["card"]["name"] == "web_search"
    assert (rows["communication"]["node"], rows["communication"]["status"]) == (False, "disabled")


def test_pause_leaves_an_agent_out_of_planning_until_resumed(client):
    assert "web_search" in client.get("/platform/agents").json()
    assert client.post("/platform/admin/agents/web_search/pause").json()["status"] == "paused"
    assert "web_search" not in client.get("/platform/agents").json()
    assert client.post("/platform/admin/agents/web_search/resume").json()["status"] == "in_process"
    assert "web_search" in client.get("/platform/agents").json()


def test_recheck_searches_the_network_again(client):
    client.get("/platform/admin/agents")
    client.searches.clear()
    assert client.post("/platform/admin/agents/rag/recheck").json()["status"] == "not_found"
    assert client.searches == [True]  # a fresh search, not the cached machine


def test_actions_on_an_agent_that_is_not_a_node_are_404(client):
    res = client.post("/platform/admin/agents/communication/pause")
    assert res.status_code == 404 and "not a node" in res.json()["detail"]


def test_policies_change_at_runtime_are_validated_and_audited(client, monkeypatch):
    monkeypatch.setattr(api, "_AUDIT", api.deque(maxlen=200))
    current = client.get("/platform/policies").json()
    res = client.put("/platform/admin/policies", json={**current, "max_replans": 1, "verify_final": False})
    assert res.status_code == 200 and res.json()["max_replans"] == 1
    assert api.default_deps().policies.max_replans == 1  # in force for the next step
    entry = client.get("/platform/admin/audit").json()[0]
    assert (entry["action"], entry["target"]) == ("policies.update", "policies")
    assert "max_replans: 2 -> 1" in entry["detail"] and "verify_final: True -> False" in entry["detail"]

    assert client.put("/platform/admin/policies", json={**current, "max_replans": -1}).status_code == 422
    assert api.default_deps().policies.max_replans == 1  # a rejected change changes nothing


def test_policies_reset_reloads_the_file(client):
    client.put("/platform/admin/policies", json={"max_replans": 0})
    assert client.post("/platform/admin/policies/reset").json()["max_replans"] == 2  # config/policies.yaml
    assert client.get("/platform/admin/audit").json()[0]["action"] == "policies.reset"


def test_agent_actions_are_in_the_audit_log(client, monkeypatch):
    monkeypatch.setattr(api, "_AUDIT", api.deque(maxlen=200))
    client.post("/platform/admin/agents/web_search/pause")
    client.post("/platform/admin/agents/web_search/resume")
    log = client.get("/platform/admin/audit").json()
    assert [(e["action"], e["target"]) for e in log] == [("agent.resume", "web_search"), ("agent.pause", "web_search")]
    assert log[1]["detail"] == "status: paused" and log[0]["by"].startswith("developer")


def test_customised_planning_text_is_what_the_supervisor_plans_with_saved_and_audited(client, monkeypatch):
    monkeypatch.setattr(api, "_AUDIT", api.deque(maxlen=200))
    text = {"when_to_use": "  Only news and prices of today.  ", "examples": ["oil price today"]}
    body = client.put("/platform/admin/agents/web_search/planning", json=text).json()
    assert body["overrides"] == {"when_to_use": "Only news and prices of today.", "examples": ["oil price today"]}
    assert body["planning_defaults"]["when_to_use"] == SEARCH.when_to_use  # what reset goes back to
    card = client.get("/platform/agents").json()["web_search"]
    assert (card["when_to_use"], card["examples"], card["description"]) == (
        "Only news and prices of today.", ["oil price today"], SEARCH.description)
    assert overrides.load() == {"web_search": body["overrides"]}  # survives a restart
    entry = client.get("/platform/admin/audit").json()[0]
    assert (entry["action"], entry["target"]) == ("agent.customise", "web_search")
    assert entry["detail"] == "when_to_use: customised; examples: customised"


def test_a_field_equal_to_the_agents_own_card_is_not_customised(client):
    body = client.put("/platform/admin/agents/web_search/planning", json={"description": SEARCH.description}).json()
    assert body["overrides"] == {} and overrides.load() == {}


def test_reset_planning_goes_back_to_the_agents_own_card(client):
    client.put("/platform/admin/agents/verifier/planning", json={"description": "Checks answers."})
    client.put("/platform/admin/agents/web_search/planning", json={"description": "Searches."})
    body = client.delete("/platform/admin/agents/web_search/planning").json()
    assert body["overrides"] == {} and body["card"]["description"] == SEARCH.description
    assert overrides.load() == {"verifier": {"description": "Checks answers."}}  # the other agents are kept
    assert client.get("/platform/admin/audit").json()[0]["detail"] == "description: the agent's own"


@pytest.mark.parametrize("text", [
    {"description": "   "},  # empty after trimming
    {"examples": []},
    {"examples": [f"example {i}" for i in range(13)]},
    {"params_schema": {}},  # only the planning text can be customised
])
def test_invalid_planning_text_is_rejected_and_changes_nothing(client, text):
    assert client.put("/platform/admin/agents/web_search/planning", json=text).status_code == 422
    assert client.get("/platform/agents").json()["web_search"]["description"] == SEARCH.description


def test_planning_text_of_an_agent_that_is_down_applies_when_its_card_comes_back(client):
    body = client.put("/platform/admin/agents/rag/planning", json={"description": "The contracts."}).json()
    assert body["overrides"] == {"description": "The contracts."}
    assert body["card"] is None and body["planning_defaults"] is None  # its card is not fetched yet
    entry = api.default_deps().registry._entries["rag"]
    entry.own = AgentCard(name="rag", version="1", description="Documents.", when_to_use="docs", when_not_to_use="web")
    assert entry.effective().description == "The contracts."


def test_planning_text_of_an_agent_that_is_not_a_node_is_404(client):
    assert client.put("/platform/admin/agents/communication/planning", json={"description": "x"}).status_code == 404


def test_saved_planning_text_is_loaded_when_the_supervisor_starts():
    overrides.save("web_search", {"when_not_to_use": "Questions about our own documents."})
    status = AgentRegistry.from_config().status("web_search")
    assert status["card"]["when_not_to_use"] == "Questions about our own documents."
    assert status["planning_defaults"]["when_not_to_use"] == SEARCH.when_not_to_use
