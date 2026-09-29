"""Human-readable terminal log for run.py: frontend | backend side by side (or stacked when the terminal is narrow).

Backend (langgraph dev) lines look like
    2026-09-28T10:45:31.644633Z [info     ] HTTP Request: GET http://... "HTTP/1.1 200 OK" [httpx] api_variant=... k=v
and become
    16:15:31  ·  GET http://... -> 200 OK                     httpx
Internal chatter (worker / queue stats, auth plumbing, model-download checks) is dropped; warnings and errors are
always kept. Frontend (ng serve) lines get a time and lose ANSI codes and build-cache noise. Everything else (the
banner, tracebacks) passes through unchanged. Standard library only: run.py imports this before checking the env.
"""

from __future__ import annotations

import re
import shutil
import sys
import textwrap
import threading
from datetime import datetime

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_BACKEND = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z?)\s+\[(\w+)\s*\]\s+(.*)$")
_LOGGER = re.compile(r"\s\[([A-Za-z_][\w.]*)\](?=\s|$)")
_HTTPX = re.compile(r'^HTTP Request: (\w+) (\S+) "HTTP/[\d.]+ (\d{3}) ?([^"]*)"')

# (logger prefix, message prefix) that are pure chatter at info level
_NOISE = (
    ("langgraph_api.metrics", ""), ("langgraph_runtime_inmem.queue", ""), ("langgraph_api.auth", ""),
    ("langgraph_api.timing", ""), ("langgraph_api.metadata", ""), ("langgraph_api.graph", ""),
    ("langgraph_api.cron_scheduler", ""), ("langgraph_runtime_inmem._persistence", ""),
    ("langgraph_runtime_inmem.lifespan", ""), ("langgraph_runtime", "Using"), ("langgraph_api.models.run", ""),
    ("langgraph_runtime_inmem.ops", ""), ("sentence_transformers", ""), ("huggingface_hub", ""),
    ("langgraph_api.server", ""), ("uvicorn", ""),
)
_NOISE_URLS = ("huggingface.co",)
_HARMLESS = ("`durability` has no effect when no checkpointer is present",)  # UI console runs: no checkpointer
_SITE_PACKAGES = re.compile(r"[A-Za-z]:[\\/]\S*?[\\/]site-packages[\\/]")
_SIZE_TABLE = re.compile(r"\|\s*[\d.]+ (kB|MB|bytes)\s*\|?|^(Initial chunk files|Lazy chunk files|\| Initial total)")
_FRONTEND_NOISE = ("re-using cached externals", "Removed unused dependencies", "Bundling shared mappings",
                   "Building federation artifacts", "Skip packages you don't want to share", "Bundling exposed modules",
                   "Re-bundling all internal libraries", "Watch mode enabled", "Page reload sent to client",
                   "NOTE: Raw file sizes do not reflect")

LEVEL = {"debug": "·", "info": "·", "warning": "!", "error": "✗", "critical": "✗", "exception": "✗"}
COLOR = {"frontend": "\033[35m", "backend": "\033[36m", "run": "\033[33m", "warn": "\033[33m", "err": "\033[31m",
         "dim": "\033[2m"}
RESET = "\033[0m"


def _local_time(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%H:%M:%S")
    except ValueError:
        return iso[11:19]


def now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def format_backend(line: str) -> tuple[str, str] | None:
    """(severity, readable text) for a langgraph dev line, None to drop it. severity: info | warn | err."""
    line = ANSI.sub("", line).rstrip()
    if not line.strip() or line.startswith("INFO:langgraph_api.cli:"):
        return None
    match = _BACKEND.match(line)
    if not match:
        if any(h in line for h in _HARMLESS):
            return None
        line = _SITE_PACKAGES.sub("…/site-packages/", line)
        return ("err" if line.lstrip().startswith(("Traceback", "raise ")) else "info", line)  # banner, tracebacks
    stamp, level, rest = match[1], match[2].lower(), match[3]
    logger_match = _LOGGER.search(rest)
    message = (rest[: logger_match.start()] if logger_match else rest).strip()
    source = logger_match[1] if logger_match else ""
    severity = "err" if level in ("error", "critical", "exception") else "warn" if level == "warning" else "info"

    if severity == "info":
        if any(source.startswith(s) and message.startswith(m) for s, m in _NOISE):
            return None
        if source == "langgraph_api.worker":  # run lifecycle: keep, short
            kv = dict(re.findall(r"(\w+)=(\S+)", rest[logger_match.end():] if logger_match else ""))
            if message.startswith("Background run succeeded"):
                ms = kv.get("run_exec_ms")
                message = f"run finished{f' in {int(ms) / 1000:.1f} s' if ms and ms.isdigit() else ''}" \
                          f" ({kv.get('graph_id', 'graph')})"
            elif message.startswith("Starting background run"):
                message = f"run started ({kv.get('graph_id', 'graph')})"
            else:
                return None
    if any(h in message for h in _HARMLESS):
        return None
    message = _SITE_PACKAGES.sub("…/site-packages/", message)
    http = _HTTPX.match(message)
    if http:
        if severity == "info" and any(u in http[2] for u in _NOISE_URLS):
            return None
        message = f"{http[1]} {http[2]} -> {http[3]} {http[4]}".rstrip()
    short = source.rsplit(".", 1)[-1] if source else ""
    short = {"user_router_module": "api", "user_graph_module": "graph"}.get(short, short)  # files loaded by path
    return severity, f"{_local_time(stamp)} {LEVEL.get(level, '·')} {message}" + (f"  [{short}]" if short else "")


def format_frontend(line: str) -> tuple[str, str] | None:
    line = ANSI.sub("", line).rstrip()
    text = re.sub(r"^\s*(INFO|NOTE)\s+", "", line.strip())
    if (not text or any(noise in text for noise in _FRONTEND_NOISE) or set(text) <= set("-=│|")
            or _SIZE_TABLE.search(text) or text.startswith("❯ ")):
        return None
    lowered = text.lower()
    severity = "err" if ("error" in lowered or text.startswith(("ERRR", "✘", "X "))) else \
        "warn" if ("warning" in lowered or text.startswith("▲")) else "info"
    return severity, f"{now()} {text}"


class Printer:
    """Prints `frontend | backend` in two columns (split) or as labelled lines (stacked). Thread-safe."""

    def __init__(self, layout: str = "auto", raw: bool = False, color: bool | None = None):
        width = shutil.get_terminal_size(fallback=(160, 40)).columns
        interactive = sys.stdout.isatty()
        self.layout = ("split" if interactive and width >= 120 else "stacked") if layout == "auto" else layout
        self.raw = raw
        self.color = interactive if color is None else color
        self.width = max(width, 80)
        self.column = (self.width - 3) // 2
        self._lock = threading.Lock()
        self._header_done = False

    def _paint(self, text: str, key: str) -> str:
        return f"{COLOR[key]}{text}{RESET}" if self.color and key in COLOR else text

    def _write(self, text: str) -> None:
        try:
            print(text, flush=True)
        except (UnicodeError, OSError):
            pass  # never let one unprintable line stop the log relay (the child would block on a full pipe)

    def header(self) -> None:
        if self.layout != "split" or self._header_done:
            return
        self._header_done = True
        left = "FRONTEND  web-search-ui :4301".ljust(self.column)
        right = "BACKEND  web-search-agent :8201"
        self._write(self._paint(left, "frontend") + " │ " + self._paint(right, "backend"))
        self._write("─" * self.column + "─┼─" + "─" * self.column)

    def run(self, message: str) -> None:
        """run.py's own messages: full width."""
        with self._lock:
            self._write(self._paint(f"[run] {message}", "run"))

    def line(self, source: str, raw_line: str) -> None:
        """A line of `frontend` or `backend` output."""
        if self.raw:
            formatted: tuple[str, str] | None = ("info", ANSI.sub("", raw_line).rstrip())
        else:
            formatted = (format_backend if source == "backend" else format_frontend)(raw_line)
        if not formatted or not formatted[1].strip():
            return
        severity, text = formatted
        with self._lock:
            if self.layout == "stacked":
                label = self._paint(f"{source:<8} │", source)
                self._write(f"{label} {self._paint(text, severity) if severity != 'info' else text}")
                return
            self.header()
            for part in textwrap.wrap(text, self.column, subsequent_indent="   ", drop_whitespace=False,
                                      replace_whitespace=False) or [""]:
                cell = part.ljust(self.column)
                cell = self._paint(cell, severity) if severity != "info" else cell
                blank = " " * self.column
                self._write(f"{cell} │ {blank}" if source == "frontend" else f"{blank} │ {cell}")
