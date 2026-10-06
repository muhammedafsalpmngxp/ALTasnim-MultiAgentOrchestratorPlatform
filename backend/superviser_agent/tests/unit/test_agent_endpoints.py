"""Every agent is a LangGraph deployment reached on its port + graph: config, network discovery and the
registry (no real network: sockets and HTTP are stubbed)."""

import httpx
import pytest
from orchestrator_agent.clients import RemoteAgentClient
from orchestrator_agent.registry import AgentRegistry, discovery
from orchestrator_agent.settings import AgentConfig, AgentsConfig, load_agents_config


def test_config_has_a_port_and_graph_per_node():
    cfg = load_agents_config()
    nodes = {name: (a.port, a.graph_id) for name, a in cfg.agents.items() if a.enabled}
    assert nodes == {"web_search": (8201, "web_search"), "rag": (8000, "rag"), "verifier": (8203, "verifier"),
                     "synthesizer": (8204, "synthesizer"), "communication": (8202, "communication")}


def test_env_overrides_each_agent_port_and_the_network(monkeypatch):
    monkeypatch.setenv("AGENT_RAG", "8010")
    monkeypatch.setenv("AGENT_SUBNET", "192.168.1.0/24")
    monkeypatch.setenv("AGENT_VERIFIER_URL", "http://192.168.1.25:8203")
    cfg = load_agents_config()
    assert cfg.agents["rag"].port == 8010
    assert cfg.subnet == "192.168.1.0/24"
    assert cfg.agents["verifier"].url == "http://192.168.1.25:8203"
    monkeypatch.setenv("AGENT_RAG", "8000/retrieve")
    with pytest.raises(ValueError, match="must be the agent's port"):
        load_agents_config()


def test_discovery_finds_the_machine_serving_the_graph(monkeypatch):
    monkeypatch.setattr(discovery, "_found", {})
    monkeypatch.setattr(discovery, "_port_open", lambda host, port: host in ("192.168.5.3", "192.168.5.9"))
    monkeypatch.setattr(discovery, "serves_graph", lambda base, graph_id: base == "http://192.168.5.9:8000")

    assert discovery.locate(8000, "rag", subnet="192.168.5.0/24") == "http://192.168.5.9:8000"
    monkeypatch.setattr(discovery, "_port_open", lambda host, port: False)  # cached until a refresh
    assert discovery.locate(8000, "rag", subnet="192.168.5.0/24") == "http://192.168.5.9:8000"
    assert discovery.locate(8000, "rag", subnet="192.168.5.0/24", refresh=True) is None


def test_serves_graph_asks_the_langgraph_api(monkeypatch):
    def post(url, json, timeout):
        assert (url, json) == ("http://10.0.0.5:8000/assistants/search", {"graph_id": "rag", "limit": 1})
        return httpx.Response(200, json=[{"assistant_id": "a1"}], request=httpx.Request("POST", url))

    monkeypatch.setattr(discovery.httpx, "post", post)
    assert discovery.serves_graph("http://10.0.0.5:8000", "rag")


def test_registry_calls_every_agent_as_a_langgraph_deployment_and_merges_cards(monkeypatch):
    cfg = AgentsConfig(transport="remote", agents={
        "web_search": AgentConfig(port=8201, graph_id="web_search"),
        "synthesizer": AgentConfig(port=8204, graph_id="synthesizer", url="http://10.0.0.4:8204",
                                   card={"when_to_use": "last step", "when_not_to_use": "finding facts"}),
        "off": AgentConfig(enabled=False, port=9999, graph_id="off"),
    })
    registry = AgentRegistry.from_config(cfg)
    assert registry.names() == ["web_search", "synthesizer"]
    assert all(isinstance(registry.client(n), RemoteAgentClient) for n in registry.names())

    monkeypatch.setattr(discovery, "locate", lambda *a, **k: None)  # web_search: no machine found

    def get(url, timeout):  # the synthesizer's own card lacks the planning fields
        assert url == "http://10.0.0.4:8204/card"
        return httpx.Response(200, json={"name": "synthesizer", "version": "0.7", "description": "answers"},
                              request=httpx.Request("GET", url))

    monkeypatch.setattr("orchestrator_agent.registry.registry.httpx.get", get)
    cards = registry.cards()
    assert list(cards) == ["synthesizer"]  # web_search is down: left out of planning
    assert (cards["synthesizer"].when_to_use, cards["synthesizer"].version) == ("last step", "0.7")


def test_an_agent_needs_its_graph_and_port():
    with pytest.raises(ValueError, match="graph_id and its port"):
        AgentRegistry.from_config(AgentsConfig(transport="remote", agents={"rag": AgentConfig(port=8000)}))
