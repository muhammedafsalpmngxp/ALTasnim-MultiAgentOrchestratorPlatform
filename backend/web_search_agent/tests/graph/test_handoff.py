"""Sending the output (question + top 3 contents) to every WEB_SEARCH_VERIFIER_PATH route found on the network."""

import asyncio
import ipaddress
import json

import httpx
import pytest
from web_search_agent.context import Context
from web_search_agent.graph import graph
from web_search_agent.services import handoff, history
from web_search_agent.settings import get_settings

from utils import AgentTask

VERDICT = {"status": "ok", "passed": True, "issues": [], "warnings": [], "summary": "Verification passed"}
ANSWER = {"answer": "V.D. Satheesan is the Chief Minister of Kerala."}
OUTPUT = {"status": "ok", "summary": "s", "question": "q", "findings": [], "sources": []}


def spec(*post_paths: str, get_paths: tuple[str, ...] = ()) -> dict:
    """A minimal OpenAPI spec, like FastAPI / langgraph dev generate."""
    paths = {p: {"post": {}} for p in post_paths}
    paths.update({p: {"get": {}} for p in get_paths})
    return {"openapi": "3.1.0", "paths": paths}


class FakeServers:
    """MockTransport for several machines: `hosts[ip] = {"spec": dict | None, "post": {path: response}}`.
    GET /openapi.json -> the spec (404 if None); GET on a POST route -> 405; POST on it -> its response."""

    def __init__(self, hosts: dict[str, dict]):
        self.hosts = hosts
        self.posts: list[tuple[str, dict]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        server = self.hosts.get(request.url.host)
        path = request.url.path
        if server is None:
            raise httpx.ConnectError("no such machine")
        if request.method == "GET":
            if path == "/openapi.json":
                return httpx.Response(200, json=server["spec"]) if server.get("spec") else httpx.Response(404)
            return httpx.Response(405 if path in server["post"] else 404)
        if path in server["post"]:
            self.posts.append((str(request.url), json.loads(request.content)))
            return httpx.Response(200, json=server["post"][path])
        return httpx.Response(404)


def with_servers(monkeypatch, servers: FakeServers, coro_factory):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(servers)) as client:
            monkeypatch.setattr(handoff, "http_client", lambda: client)
            return await coro_factory()

    return asyncio.run(go())


def configure(monkeypatch, **env: str) -> None:
    for key, value in env.items():
        monkeypatch.setenv(f"WEB_SEARCH_{key.upper()}", value)
    get_settings.cache_clear()


def on_network(monkeypatch, servers: FakeServers, own: str = "192.168.1.2") -> None:
    """The machines of `servers` are the only ones listening; this machine is `own`."""
    monkeypatch.setattr(handoff, "local_ipv4", lambda: [own])

    async def port_open(host, port, timeout):
        return host in servers.hosts

    monkeypatch.setattr(handoff, "_port_open", port_open)


@pytest.fixture(autouse=True)
def fresh_discovery(monkeypatch):
    monkeypatch.setattr(handoff, "_found", {})
    monkeypatch.setattr(handoff, "_open", {})


def run(objective: str = "iPhone price in Oman") -> tuple[dict, dict]:
    inputs = {"task": AgentTask(task_id="s1", objective=objective).model_dump()}
    result = asyncio.run(graph.ainvoke(inputs, context=Context(trace_id="t-1")))["result"]
    return result, history.get("t-1")


def send_step(details: dict) -> dict:
    return next(s for s in details["steps"] if s["id"] == "verify")


# --- settings ---------------------------------------------------------------------------------
def test_the_path_list_is_normalised(monkeypatch):
    configure(monkeypatch, verifier_path=" /verify, synthesize/ ,/Verify,, /api/check ", verifier_port="8203, 8230")
    assert get_settings().output_paths == ["/verify", "/synthesize", "/Verify", "/api/check"]
    assert get_settings().output_ports == [8203, 8230]
    configure(monkeypatch, verifier_path="")
    assert get_settings().output_paths == []


def test_one_body_serves_the_verifier_and_the_synthesizer():
    result = {**OUTPUT, "question": "who is the chief minister of kerala"}
    payload = handoff.body("s1", result)
    assert payload["task"]["task_id"] == "verify-s1" and payload["task"]["inputs"] == {"s1": result}
    assert payload["question"] == "who is the chief minister of kerala"
    assert payload["inputs"] == {"web_search": result}


# --- which routes a server has ----------------------------------------------------------------
def test_post_routes_from_an_openapi_spec():
    langgraph_dev = spec("/threads", "/runs/wait", "/Verify/", "/threads/{thread_id}/runs", get_paths=("/card",))
    assert handoff.post_routes(langgraph_dev) == {"/threads": "/threads", "/runs/wait": "/runs/wait",
                                                  "/verify": "/Verify/"}
    assert handoff.post_routes({"paths": "broken"}) == {} and handoff.post_routes(None) == {}


def test_routes_on_a_server_from_its_spec_or_by_probing(monkeypatch):
    servers = FakeServers({
        "192.168.1.25": {"spec": spec("/runs/wait", "/verify"), "post": {"/verify": {}}},
        "192.168.1.33": {"spec": None, "post": {"/synthesize": {}}},  # plain FastAPI without a spec
        "192.168.1.40": {"spec": spec("/rag/query"), "post": {"/rag/query": {}}},
    })
    wanted = ["/verify", "/synthesize"]
    found = with_servers(monkeypatch, servers, lambda: asyncio.gather(
        *(handoff.routes_on(f"http://192.168.1.{h}:8203", wanted) for h in (25, 33, 40))))
    assert found == [["/verify"], ["/synthesize"], []]


# --- the whole network --------------------------------------------------------------------------
def test_the_output_goes_to_every_route_found_on_the_network(monkeypatch):
    configure(monkeypatch, verifier_path="/verify,/synthesize", discovery_subnets="192.168.1.0/26")
    servers = FakeServers({
        "192.168.1.25": {"spec": spec("/runs/wait", "/verify"), "post": {"/verify": {"result": VERDICT}}},
        "192.168.1.33": {"spec": spec("/synthesize"), "post": {"/synthesize": ANSWER}},
        "192.168.1.40": {"spec": spec("/rag/query"), "post": {"/rag/query": {}}},  # another agent: not listed
    })
    on_network(monkeypatch, servers)
    records = with_servers(monkeypatch, servers, lambda: handoff.deliver("s1", OUTPUT))

    by_url = {r["url"]: r for r in records}
    assert set(by_url) == {"http://192.168.1.25:8203/verify", "http://192.168.1.33:8203/synthesize"}
    assert by_url["http://192.168.1.25:8203/verify"]["passed"] is True
    assert by_url["http://192.168.1.33:8203/synthesize"] == {
        "url": "http://192.168.1.33:8203/synthesize", "path": "/synthesize", "host": "192.168.1.33",
        "status": "sent", "response": ANSWER}
    assert sorted(u for u, _ in servers.posts) == sorted(by_url)  # nothing sent to 192.168.1.40
    assert all(p == handoff.body("s1", OUTPUT) for _, p in servers.posts)


def test_this_machine_is_used_once_not_on_its_lan_address_and_localhost(monkeypatch):
    configure(monkeypatch, verifier_path="/verify", discovery_subnets="192.168.1.0/29")
    servers = FakeServers({"192.168.1.2": {"spec": spec("/verify"), "post": {"/verify": VERDICT}},
                           "127.0.0.1": {"spec": spec("/verify"), "post": {"/verify": VERDICT}}})
    on_network(monkeypatch, servers, own="192.168.1.2")
    urls = with_servers(monkeypatch, servers, handoff.endpoints)
    assert urls == ["http://192.168.1.2:8203/verify"]


def test_several_ports(monkeypatch):
    configure(monkeypatch, verifier_path="/synthesize", verifier_port="8203,8230", discovery_subnets="192.168.1.0/29")
    servers = FakeServers({"192.168.1.3": {"spec": spec("/synthesize"), "post": {"/synthesize": ANSWER}}})
    on_network(monkeypatch, servers)
    urls = with_servers(monkeypatch, servers, handoff.endpoints)
    assert urls == ["http://192.168.1.3:8203/synthesize", "http://192.168.1.3:8230/synthesize"]


def test_nothing_on_the_network_is_reported(monkeypatch):
    configure(monkeypatch, verifier_path="/verify,/synthesize", discovery_subnets="192.168.1.0/29")
    on_network(monkeypatch, FakeServers({}))
    with pytest.raises(handoff.TargetNotFound,
                       match="no machine with /verify, /synthesize on port 8203 in 192.168.1.0/29"):
        with_servers(monkeypatch, FakeServers({}), handoff.endpoints)


def test_a_moved_machine_is_found_again(monkeypatch):
    configure(monkeypatch, verifier_path="/verify", discovery_subnets="192.168.1.0/28")
    servers = FakeServers({"192.168.1.5": {"spec": spec("/verify"), "post": {"/verify": VERDICT}}})
    on_network(monkeypatch, servers)
    monkeypatch.setattr(handoff.asyncio, "sleep", _no_sleep)

    async def go():
        first = await handoff.deliver("s1", OUTPUT)
        servers.hosts = {"192.168.1.9": servers.hosts.pop("192.168.1.5")}  # the verifier moved
        second = await handoff.deliver("s1", OUTPUT)  # cached .5 fails -> one new scan -> .9
        return first, second

    first, second = with_servers(monkeypatch, servers, go)
    assert [r["url"] for r in first] == ["http://192.168.1.5:8203/verify"]
    assert [(r["url"], r["status"]) for r in second] == [("http://192.168.1.5:8203/verify", "failed"),
                                                         ("http://192.168.1.9:8203/verify", "sent")]


def test_a_flapping_host_is_still_found(monkeypatch):
    """Measured on the real network: only 7 of 20 connects to the synthesizer machine succeeded."""
    configure(monkeypatch, verifier_path="/synthesize", discovery_subnets="192.168.1.0/30")
    monkeypatch.setattr(handoff, "local_ipv4", lambda: ["192.168.1.2"])
    tries: list[str] = []

    async def port_open(host, port, timeout):
        tries.append(host)
        return host == "192.168.1.1" and tries.count(host) == 2  # answers only the second time

    async def routes_on(base, wanted):
        return ["/synthesize"]

    monkeypatch.setattr(handoff, "_port_open", port_open)
    monkeypatch.setattr(handoff, "routes_on", routes_on)
    assert asyncio.run(handoff.endpoints()) == ["http://192.168.1.1:8203/synthesize"]


def test_a_post_is_retried_on_connection_errors(monkeypatch):
    monkeypatch.setattr(handoff.asyncio, "sleep", _no_sleep)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        if len(calls) < 3:
            raise httpx.ConnectError("[WinError 10060] connection timed out")
        return httpx.Response(200, json={"result": VERDICT})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            monkeypatch.setattr(handoff, "http_client", lambda: client)
            return await handoff.send_to("http://192.168.1.25:8203/verify", {})

    assert asyncio.run(go()) == VERDICT and calls == ["POST", "POST", "POST"]


def test_candidate_hosts_this_machine_last_and_subnets_can_be_set(monkeypatch):
    configure(monkeypatch, discovery_subnets="10.0.0.0/30")
    monkeypatch.setattr(handoff, "local_ipv4", lambda: ["10.0.0.2"])
    assert handoff.networks() == [ipaddress.ip_network("10.0.0.0/30")]
    assert handoff.candidate_hosts() == ["10.0.0.1", "10.0.0.2", "127.0.0.1"]


def test_port_probe_on_a_closed_port():
    assert asyncio.run(handoff._port_open("127.0.0.1", 1, 0.3)) is False


# --- the node -------------------------------------------------------------------------------------
def test_the_node_sends_and_records_one_entry_per_url(fake_web, monkeypatch):
    configure(monkeypatch, verifier_path="/verify,/synthesize")

    async def deliver(step_id, result):
        assert step_id == "s1" and set(result) == {"status", "summary", "question", "findings", "sources"}
        return [handoff._record("http://192.168.1.25:8203/verify", VERDICT),
                handoff._record("http://192.168.1.33:8203/synthesize", ANSWER)]

    monkeypatch.setattr(handoff, "deliver", deliver)
    result, details = run()
    assert result["status"] == "ok"
    assert set(details["handoffs"]) == {"http://192.168.1.25:8203/verify", "http://192.168.1.33:8203/synthesize"}
    assert details["verification"]["passed"] is True  # the first verdict
    step = send_step(details)
    assert step["status"] == "done" and step["title"] == "Send output"
    assert "/verify @ 192.168.1.25: Verification passed" in step["detail"]
    assert "/synthesize @ 192.168.1.33: sent" in step["detail"]


def test_a_route_not_found_is_listed_and_a_failure_does_not_fail_the_search(fake_web, monkeypatch):
    configure(monkeypatch, verifier_path="/verify,/synthesize")

    async def deliver(step_id, result):
        return [handoff._record("http://192.168.1.33:8203/synthesize", error=httpx.ConnectError("timed out"))]

    monkeypatch.setattr(handoff, "deliver", deliver)
    result, details = run()
    assert result["status"] == "ok" and result["findings"]
    step = send_step(details)
    assert step["status"] == "failed"
    assert "not found on the network: /verify" in step["detail"]
    assert any("/synthesize @ 192.168.1.33 not reachable" in w for w in details["warnings"])


def test_nothing_configured_is_skipped(fake_web):
    _, details = run()
    assert send_step(details)["status"] == "skipped" and details["handoffs"] == {}
    assert details["verification"] == {"status": "not_configured", "url": None}


def test_discovery_makes_no_blocking_calls_on_the_event_loop(monkeypatch):
    """langgraph dev raises BlockingError for sync socket calls in the event loop (blockbuster): run a real,
    tiny scan (this machine only, a closed port) under the same checker."""
    blockbuster = pytest.importorskip("blockbuster")
    configure(monkeypatch, verifier_path="/verify", discovery_subnets="127.0.0.0/30", verifier_port="1",
              discovery_scan_timeout_seconds="0.2", discovery_attempts="1")
    get_settings()  # the server loads settings at import time, before the event loop runs

    async def scan():
        with blockbuster.blockbuster_ctx():
            with pytest.raises(handoff.TargetNotFound, match="no machine with /verify on port 1 in 127.0.0.0/30"):
                await handoff.endpoints()

    asyncio.run(scan())


async def _no_sleep(_seconds):
    return None
