"""Finding the synthesizer on the LAN: port open + path in /openapi.json; this machine is skipped."""

import asyncio

import pytest
from verifier_agent import discovery


@pytest.fixture(autouse=True)
def _network(monkeypatch):
    discovery._found.clear()
    monkeypatch.delenv("VERIFIER_SYNTHESIZER_URL", raising=False)
    monkeypatch.setenv("VERIFIER_SYNTHESIZER_PORT", "8204")
    monkeypatch.setenv("VERIFIER_SYNTHESIZER_PATH", "/synthesize")
    monkeypatch.setattr(discovery, "_hosts", lambda: ["192.168.1.10", "192.168.1.22", "192.168.1.30"])
    monkeypatch.setattr(discovery, "_own_ips", lambda: {"127.0.0.1", "192.168.1.30"})
    probed = []

    async def port_open(host, port):
        probed.append(host)
        return host in {"192.168.1.10", "192.168.1.22", "192.168.1.30"}

    async def has_path(client, base_url, path):
        return base_url == "http://192.168.1.22:8204" and path == "/synthesize"  # .10 is another service

    monkeypatch.setattr(discovery, "_port_open", port_open)
    monkeypatch.setattr(discovery, "_has_path", has_path)
    yield probed
    discovery._found.clear()


def test_finds_the_machine_that_serves_the_path(_network):
    assert asyncio.run(discovery.synthesizer_url()) == "http://192.168.1.22:8204/synthesize"
    assert "192.168.1.30" not in _network  # this machine is never probed


def test_found_machine_is_cached(_network):
    asyncio.run(discovery.synthesizer_url())
    _network.clear()
    assert asyncio.run(discovery.synthesizer_url()) == "http://192.168.1.22:8204/synthesize"
    assert _network == []


def test_fixed_url_skips_the_search(monkeypatch, _network):
    monkeypatch.setenv("VERIFIER_SYNTHESIZER_URL", "http://10.0.0.5:9000/synthesize")
    assert asyncio.run(discovery.synthesizer_url()) == "http://10.0.0.5:9000/synthesize"
    assert _network == []


def test_empty_path_turns_forwarding_off(monkeypatch, _network):
    monkeypatch.setenv("VERIFIER_SYNTHESIZER_PATH", "")
    assert asyncio.run(discovery.synthesizer_url()) is None
    assert _network == []
