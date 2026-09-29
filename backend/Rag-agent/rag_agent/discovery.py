"""Finds each next agent on the LAN automatically: for an endpoint PORT/PATH, a host that has PORT open
and whose API lists PATH (e.g. /synthesize) in its /openapi.json. Other services on the same port (such
as a teammate's verifier agent on 8203) are skipped, and no document data is sent while searching.
No machine IP is configured; each endpoint's machine is cached until a call to it fails."""

import ipaddress
import logging
import socket
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx

from .config import settings

log = logging.getLogger("rag_agent")
_lock = threading.Lock()
_found: dict[tuple[int, str], str] = {}  # (port, path) -> base URL, e.g. http://192.168.1.33:8203


def _subnets() -> list[ipaddress.IPv4Network]:
    """NEXT_AGENT_SUBNET (comma-separated CIDRs), else this machine's own /24 (works outside Docker)."""
    if settings.next_agent_subnet:
        cidrs = [s.strip() for s in settings.next_agent_subnet.split(",") if s.strip()]
        return [ipaddress.ip_network(cidr, strict=False) for cidr in cidrs]
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("10.255.255.255", 1))  # UDP connect sends nothing; it just picks the outgoing interface
        own_ip = s.getsockname()[0]
    return [ipaddress.ip_network(f"{own_ip}/24", strict=False)]


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _has_endpoint(base_url: str, path: str) -> bool:
    """True if the service's OpenAPI lists `path`. Read-only; sends no document data."""
    try:
        paths = httpx.get(f"{base_url}/openapi.json", timeout=3).json().get("paths", {})
    except (httpx.HTTPError, ValueError, AttributeError):
        return False
    return path in paths


def discover(port: int, path: str) -> str | None:
    """Scan the subnets for hosts with `port` open; return the first one serving `path`."""
    hosts = [str(h) for net in _subnets() for h in net.hosts()]
    with ThreadPoolExecutor(max_workers=64) as pool:
        open_hosts = [h for h, is_open in zip(hosts, pool.map(lambda h: _port_open(h, port), hosts), strict=True)
                      if is_open]
    for host in open_hosts:
        base_url = f"http://{host}:{port}"
        if _has_endpoint(base_url, path):
            log.info("next agent %s%s found at %s (port open on: %s)", port, path, base_url, open_hosts)
            return base_url
    log.warning("no machine with port %s open serves %s (port open on: %s)", port, path, open_hosts or "none")
    return None


def next_agent_url(port: int, path: str, refresh: bool = False) -> str | None:
    """Full URL to POST to for PORT/PATH (cached; `refresh` scans again), or None if not found."""
    with _lock:
        key = (port, path)
        if refresh or key not in _found:
            base_url = discover(port, path)
            if base_url:
                _found[key] = base_url
            else:
                _found.pop(key, None)
        return f"{_found[key]}{path}" if key in _found else None
