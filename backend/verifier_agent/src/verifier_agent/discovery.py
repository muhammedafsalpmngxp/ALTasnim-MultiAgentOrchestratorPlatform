"""Finds the synthesizer on the LAN: a machine with ``VERIFIER_SYNTHESIZER_PORT`` (8204) open whose API lists
``VERIFIER_SYNTHESIZER_PATH`` (/synthesize) in its ``/openapi.json``. This machine's own addresses are skipped,
so a local synthesizer is never picked. No data is sent while searching. The machine found is cached until a
POST to it fails; ``VERIFIER_SYNTHESIZER_URL`` set to a full URL skips the search.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import socket

import httpx

logger = logging.getLogger(__name__)

MAX_HOSTS = 4096  # never probe more than this many addresses (e.g. a wrongly configured /16)
CONNECT_TIMEOUT = 0.5
SCAN_CONCURRENCY = 256

_found: dict[tuple[int, str], str] = {}  # (port, path) -> full URL
_locks: dict[int, asyncio.Lock] = {}  # per event loop (a Lock belongs to its loop)


def target() -> tuple[int, str] | None:
    """(port, path) to search for, or None when forwarding is off (VERIFIER_SYNTHESIZER_PATH empty)."""
    path = os.getenv("VERIFIER_SYNTHESIZER_PATH", "").strip()
    if not path:
        return None
    return int(os.getenv("VERIFIER_SYNTHESIZER_PORT", "8204")), "/" + path.lstrip("/")


async def synthesizer_url(refresh: bool = False) -> str | None:
    """The URL to POST the verdict to: VERIFIER_SYNTHESIZER_URL if set, else the machine found on the LAN."""
    fixed = os.getenv("VERIFIER_SYNTHESIZER_URL", "").strip()
    if fixed:
        return fixed
    key = target()
    if key is None:
        return None
    async with _locks.setdefault(id(asyncio.get_running_loop()), asyncio.Lock()):
        if refresh or key not in _found:
            url = await discover(*key)
            if url:
                _found[key] = url
            else:
                _found.pop(key, None)
        return _found.get(key)


async def discover(port: int, path: str) -> str | None:
    # Socket lookups block; run them off the event loop (langgraph dev rejects blocking calls in it).
    all_hosts, own = await asyncio.gather(asyncio.to_thread(_hosts), asyncio.to_thread(_own_ips))
    hosts = [h for h in all_hosts if h not in own]
    sem = asyncio.Semaphore(SCAN_CONCURRENCY)

    async def probe(host: str) -> str | None:
        async with sem:
            return host if await _port_open(host, port) else None

    open_hosts = [h for h in await asyncio.gather(*(probe(h) for h in hosts)) if h]
    async with httpx.AsyncClient(timeout=3) as client:
        for host in open_hosts:
            if await _has_path(client, f"http://{host}:{port}", path):
                url = f"http://{host}:{port}{path}"
                logger.info("Synthesizer found at %s (port %s open on: %s)", url, port, open_hosts)
                return url
    logger.warning("No other machine with port %s open serves %s (port open on: %s)", port, path,
                   open_hosts or "none")
    return None


def _hosts() -> list[str]:
    """VERIFIER_DISCOVERY_SUBNETS (comma-separated CIDRs), else this machine's own /24."""
    cidrs = [c.strip() for c in os.getenv("VERIFIER_DISCOVERY_SUBNETS", "").split(",") if c.strip()]
    nets = [ipaddress.ip_network(c, strict=False) for c in cidrs] or [
        ipaddress.ip_network(f"{_primary_ip()}/24", strict=False)]
    return [str(h) for net in nets for h in net.hosts()][:MAX_HOSTS]


def _primary_ip() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("10.255.255.255", 1))  # UDP connect sends nothing; it just picks the outgoing interface
        return s.getsockname()[0]


def _own_ips() -> set[str]:
    ips = {"127.0.0.1"}
    try:
        ips.add(_primary_ip())
        ips.update(info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET))
    except OSError:
        pass
    return ips


async def _port_open(host: str, port: int) -> bool:
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), CONNECT_TIMEOUT)
    except (TimeoutError, OSError):
        return False
    writer.close()
    return True


async def _has_path(client: httpx.AsyncClient, base_url: str, path: str) -> bool:
    """True if the service's OpenAPI lists `path`. Read-only; sends no data."""
    try:
        return path in (await client.get(f"{base_url}/openapi.json")).json().get("paths", {})
    except (httpx.HTTPError, ValueError, AttributeError):
        return False
