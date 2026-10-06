"""Finds each agent's machine on the network, from its port and graph only (no IPs in the config).

An agent is a LangGraph deployment: a host with its port open that serves its graph (``POST /assistants/search``).
Other services on the same port are skipped, and only read-only requests are made while searching. The machine
is remembered until a call to it fails.

This machine first: ``AGENT_LOCAL_HOSTS`` (comma-separated; default ``localhost,host.docker.internal``, i.e. this
PC also from inside a container). An agent running here always wins over the same agent on a teammate's machine.
Then the networks: ``AGENT_SUBNET`` (comma-separated, e.g. 192.168.1.0/24), else this machine's own /24 (in Docker,
the compose network; set the LAN to find teammates' machines).
"""

from __future__ import annotations

import ipaddress
import logging
import os
import socket
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx

log = logging.getLogger(__name__)
_lock = threading.Lock()
_found: dict[tuple[int, str], str] = {}  # (port, graph_id) -> base URL, e.g. http://192.168.1.33:8000
DEFAULT_LOCAL_HOSTS = "localhost,host.docker.internal"


def local_hosts() -> list[str]:
    """This machine's names, searched before the network (AGENT_LOCAL_HOSTS; empty = network only)."""
    value = os.getenv("AGENT_LOCAL_HOSTS", DEFAULT_LOCAL_HOSTS)
    return [h.strip() for h in value.split(",") if h.strip()]


def subnets(value: str) -> list[ipaddress.IPv4Network]:
    if cidrs := [c.strip() for c in value.split(",") if c.strip()]:
        return [ipaddress.ip_network(cidr, strict=False) for cidr in cidrs]
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("10.255.255.255", 1))  # sends nothing; picks the outgoing interface
        own_ip = s.getsockname()[0]
    return [ipaddress.ip_network(f"{own_ip}/24", strict=False)]


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def serves_graph(base_url: str, graph_id: str) -> bool:
    try:
        res = httpx.post(f"{base_url}/assistants/search", json={"graph_id": graph_id, "limit": 1}, timeout=3)
        return res.is_success and bool(res.json())
    except (httpx.HTTPError, ValueError):
        return False


def locate(port: int, graph_id: str, *, subnet: str = "", refresh: bool = False) -> str | None:
    """Base URL of the machine serving the graph on the port (cached; ``refresh`` searches again), or None."""
    key = (port, graph_id)
    with _lock:
        if not refresh and key in _found:
            return _found[key]
    # searched outside the lock, so the agents are searched in parallel. This machine first, then the network.
    found = next((f"http://{h}:{port}" for h in local_hosts()
                  if _port_open(h, port) and serves_graph(f"http://{h}:{port}", graph_id)), None)
    open_hosts: list[str] = []
    if not found:
        hosts = [str(h) for net in subnets(subnet) for h in net.hosts()]
        with ThreadPoolExecutor(max_workers=64) as pool:
            open_hosts = [h for h, up in zip(hosts, pool.map(lambda h: _port_open(h, port), hosts), strict=True) if up]
        found = next((base for base in (f"http://{h}:{port}" for h in open_hosts) if serves_graph(base, graph_id)),
                     None)
    if found:
        log.info("agent %s (graph %s) found at %s", port, graph_id, found)
    else:
        log.warning("no machine with port %s open serves graph %s (port open on: %s)",
                    port, graph_id, open_hosts or "none")
    with _lock:
        if found:
            _found[key] = found
        else:
            _found.pop(key, None)
    return found
