"""LAN discovery of the next agents (no real network scan: the port check is faked, except one local test)."""

import dataclasses
import ipaddress
import socket

import httpx
import pytest
from rag_agent import discovery
from rag_agent.config import parse_endpoints


@pytest.fixture
def config(monkeypatch):
    def set_config(**changes):
        monkeypatch.setattr(discovery, "settings", dataclasses.replace(discovery.settings, **changes))
    set_config(next_agent_subnet="192.168.1.0/24")
    monkeypatch.setattr(discovery, "_found", {})
    return set_config


def test_parse_endpoints():
    assert parse_endpoints("8203/synthesize, 8210/answer ,") == ((8203, "/synthesize"), (8210, "/answer"))
    assert parse_endpoints("") == ()
    with pytest.raises(ValueError, match="PORT/PATH"):
        parse_endpoints("synthesize")


def test_subnets_from_config(config):
    config(next_agent_subnet="192.168.1.0/24, 10.0.0.0/30")
    assert discovery._subnets() == [ipaddress.ip_network("192.168.1.0/24"), ipaddress.ip_network("10.0.0.0/30")]


def test_subnet_defaults_to_own_network(config):
    config(next_agent_subnet="")
    [net] = discovery._subnets()
    assert net.prefixlen == 24


def test_discover_skips_other_services_on_the_same_port(config, monkeypatch):
    # .25 runs a verifier agent on 8203, .33 the synthesizer: only .33 serves /synthesize
    monkeypatch.setattr(discovery, "_port_open", lambda host, port: host in ("192.168.1.25", "192.168.1.33"))
    probed = []

    def has_endpoint(base_url, path):
        probed.append((base_url, path))
        return base_url == "http://192.168.1.33:8203"

    monkeypatch.setattr(discovery, "_has_endpoint", has_endpoint)
    assert discovery.discover(8203, "/synthesize") == "http://192.168.1.33:8203"
    assert probed == [("http://192.168.1.25:8203", "/synthesize"), ("http://192.168.1.33:8203", "/synthesize")]


def test_discover_checks_the_whole_subnet_and_finds_nothing(config, monkeypatch):
    checked = []
    monkeypatch.setattr(discovery, "_port_open", lambda host, port: checked.append((host, port)) and False)
    assert discovery.discover(8203, "/synthesize") is None
    assert sorted(checked) == sorted((f"192.168.1.{i}", 8203) for i in range(1, 255))


def test_has_endpoint_reads_openapi_paths(monkeypatch):
    specs = {
        "http://synth:8203/openapi.json": {"paths": {"/ok": {}, "/synthesize": {}}},
        "http://verifier:8203/openapi.json": {"paths": {"/ok": {}, "/card": {}}},
    }

    def get(url, timeout):
        if url not in specs:
            raise httpx.ConnectError("refused", request=httpx.Request("GET", url))
        return httpx.Response(200, json=specs[url], request=httpx.Request("GET", url))

    monkeypatch.setattr(discovery.httpx, "get", get)
    assert discovery._has_endpoint("http://synth:8203", "/synthesize")
    assert not discovery._has_endpoint("http://verifier:8203", "/synthesize")
    assert not discovery._has_endpoint("http://down:8203", "/synthesize")


def test_urls_are_cached_per_endpoint_until_refresh(config, monkeypatch):
    found = {(8203, "/synthesize"): iter(["http://192.168.1.33:8203", "http://192.168.1.40:8203"]),
             (8210, "/answer"): iter(["http://192.168.1.50:8210"])}
    monkeypatch.setattr(discovery, "discover", lambda port, path: next(found[(port, path)]))
    assert discovery.next_agent_url(8203, "/synthesize") == "http://192.168.1.33:8203/synthesize"
    assert discovery.next_agent_url(8210, "/answer") == "http://192.168.1.50:8210/answer"
    assert discovery.next_agent_url(8203, "/synthesize") == "http://192.168.1.33:8203/synthesize"  # cached
    assert discovery.next_agent_url(8203, "/synthesize", refresh=True) == "http://192.168.1.40:8203/synthesize"


def test_not_found_is_not_cached(config, monkeypatch):
    results = iter([None, "http://192.168.1.33:8203"])
    monkeypatch.setattr(discovery, "discover", lambda port, path: next(results))
    assert discovery.next_agent_url(8203, "/synthesize") is None
    assert discovery.next_agent_url(8203, "/synthesize") == "http://192.168.1.33:8203/synthesize"  # searched again


def test_port_open_on_a_real_local_socket():
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        assert discovery._port_open("127.0.0.1", port)
    assert not discovery._port_open("127.0.0.1", port)  # closed now
