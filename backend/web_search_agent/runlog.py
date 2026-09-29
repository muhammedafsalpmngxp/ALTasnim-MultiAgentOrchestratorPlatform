"""Human-readable terminal log for run.py: one stream, one line per event, the source in its own column.

    11:27:48  backend   Output goes to http://192.168.1.30:8203/verify  (searched port 8203 in 4.6 s)
    11:27:50  frontend  ✓ UI built in 1.8 s
    11:28:07  backend   ▶ Search "latest solid-state battery news"  (from web-search-ui, trace 3fa2c1d0)
    11:28:09  backend     ✓ Query planner    3 queries by gpt-4o-mini, past week (1.9 s): q1 | q2 | q3
    11:28:14  backend     ✓ Send output      /verify @ 192.168.1.30: passed (0.8 s)
    11:28:14  backend   ■ Done in 7.4 s: 3 contents, /verify passed  (trace 3fa2c1d0)

Backend (langgraph dev) lines like
    2026-09-28T10:45:31.644633Z [info     ] <message> [web_search_agent.steps] api_variant=... k=v
lose the timestamp format, the logger name and the key=value tail. The agent logs every finished pipeline step
(steps.log_step), so per-request HTTP lines, server internals (worker / queue stats, auth plumbing, model-download
checks) and the startup banner are dropped - ``verbose`` shows the HTTP requests again, ``raw`` shows everything as is.
Warnings and errors are always kept. Frontend (ng serve) lines lose ANSI codes, npm / vite / build-table noise.
Standard library only: run.py imports this before checking the environment.
"""

from __future__ import annotations

import re
import shutil
import sys
import textwrap
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

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
    ("langgraph_api.worker", ""),  # run started / succeeded: the agent logs its own ▶ / ■ lines
)
# Loggers of this agent: no [source] tag (langgraph dev loads api.py / graph.py by path under these names)
_OWN = ("web_search_agent", "user_router_module", "user_graph_module", "utils")
_HARMLESS = ("`durability` has no effect when no checkpointer is present",)  # UI console runs: no checkpointer
_SHORTER = {  # long, known warnings -> one line
    "Custom auth has no handler registered": "Custom auth: no resource-level handlers registered (fine for the dev "
                                             "server)",
    "Import for custom app": "api.py was slow to import (torch / sentence-transformers) - normal on the first start",
}
# The langgraph dev banner: run.py prints its own "Ready" box with the URLs
_BANNER = ("Welcome to", "╦", "║", "╩", "- 🚀", "- 🎨", "- 📚", "smith.langchain.com/studio", "This in-memory server",
           "For production use")
# Other lines of no use to a reader: progress bars (model loading), the tail of the slow-import warning
_PROGRESS = re.compile(r"^.{0,60}:\s+\d{1,3}%\|")
_DROP = ("FF_PROFILE_IMPORTS",)
_TRACEBACK = re.compile(r"^(Traceback \(most recent|\s+File \"|\s+raise |[\w.]+(Error|Exception|Interrupt)\b:?)")
_SITE_PACKAGES = re.compile(r"[A-Za-z]:[\\/]\S*?[\\/]site-packages[\\/]")

_SIZE_TABLE = re.compile(r"\|\s*[\d.]+ (kB|MB|bytes)\s*\|?|^(Initial chunk files|Lazy chunk files|\| Initial total)")
_BUILT = re.compile(r"^Application bundle generation (complete|failed)\. \[([\d.]+) seconds\]")
_VITE = re.compile(r"^\d\d?:\d\d:\d\d\s*(am|pm)?\s*\[vite\]\s*(\(\w+\)\s*)?", re.IGNORECASE)
_FRONTEND_NOISE = ("re-using cached externals", "Removed unused dependencies", "Bundling shared mappings",
                   "Building federation artifacts", "Skip packages you don't want to share", "Bundling exposed modules",
                   "Re-bundling all internal libraries", "Watch mode enabled", "Page reload sent to client",
                   "Component update sent to client", "NOTE: Raw file sizes do not reflect", "[Federation SSE]",
                   "Building...", "press h + enter", "Local:", "Network:", "Changes detected. Rebuilding")

COLOR = {"frontend": "\033[35m", "backend": "\033[36m", "run": "\033[33m", "warn": "\033[33m", "err": "\033[31m",
         "ok": "\033[32m", "dim": "\033[2m", "bold": "\033[1m"}
RESET = "\033[0m"


@dataclass
class Entry:
    """One readable line: severity info | warn | err, local time HH:MM:SS, text."""

    severity: str
    time: str
    text: str


def _local_time(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%H:%M:%S")
    except ValueError:
        return iso[11:19]


def now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def format_backend(line: str, verbose: bool = False) -> Entry | None:
    """A langgraph dev line as an Entry, or None to drop it."""
    line = ANSI.sub("", line).rstrip()
    if not line.strip() or line.startswith("INFO:langgraph_api.cli:"):
        return None
    match = _BACKEND.match(line)
    if not match:  # the banner, tracebacks, print() output
        if (any(h in line for h in (*_HARMLESS, *_BANNER, *_DROP)) or _PROGRESS.match(line)):
            return None
        line = _SITE_PACKAGES.sub("…/site-packages/", line)
        return Entry("err" if _TRACEBACK.match(line) else "info", now(), line)
    stamp, level, rest = match[1], match[2].lower(), match[3]
    logger_match = _LOGGER.search(rest)
    message = (rest[: logger_match.start()] if logger_match else rest).strip()
    source = logger_match[1] if logger_match else ""
    severity = "err" if level in ("error", "critical", "exception") else "warn" if level == "warning" else "info"

    if severity == "info" and any(source.startswith(s) and message.startswith(m) for s, m in _NOISE):
        return None
    if any(h in message for h in _HARMLESS):
        return None
    for known, short in _SHORTER.items():
        if message.startswith(known):
            severity, message = "info", short
    http = _HTTPX.match(message)
    if http:
        if severity == "info" and not verbose:
            return None  # the step lines say what the requests were for
        message = f"{http[1]} {http[2].split('?')[0]} -> {http[3]} {http[4]}".rstrip()
    message = _SITE_PACKAGES.sub("…/site-packages/", message)
    if source.startswith("web_search_agent.steps"):
        message = "  " + message  # steps belong to the ▶ Search line above them
    elif source and not source.startswith(_OWN):
        message += f"  [{source.split('.')[0]}]"
    return Entry(severity, _local_time(stamp), message)


def format_frontend(line: str) -> Entry | None:
    """An ng serve line as an Entry, or None to drop it."""
    line = ANSI.sub("", line).rstrip()
    text = re.sub(r"^\s*(INFO|NOTE)\s+", "", line.strip())
    if (not text or text.startswith(("> ", "❯ ")) or any(noise in text for noise in _FRONTEND_NOISE)
            or set(text) <= set("-=│|") or _SIZE_TABLE.search(text)):
        return None
    built = _BUILT.match(text)
    if built:
        seconds = float(built[2])
        if built[1] == "complete":
            return Entry("ok", now(), f"✓ UI built in {seconds:.1f} s")
        return Entry("err", now(), f"✗ UI build failed ({seconds:.1f} s)")
    lowered = text.lower()
    severity = "err" if ("error" in lowered or text.startswith(("ERRR", "✘", "X "))) else \
        "warn" if ("warning" in lowered or text.startswith("▲")) else "info"
    vite = _VITE.match(text)
    if vite:
        if severity == "info":
            return None  # dependency optimisation, HMR updates
        text = "vite: " + text[vite.end():]
    return Entry(severity, now(), text)


class Printer:
    """Writes the log: one labelled stream (stacked, default) or frontend | backend columns (split). Thread-safe.
    With ``log_file`` every line is also written there without colours."""

    def __init__(self, layout: str = "auto", raw: bool = False, color: bool | None = None, verbose: bool = False,
                 log_file: Path | None = None):
        width = shutil.get_terminal_size(fallback=(160, 40)).columns
        interactive = sys.stdout.isatty()
        self.layout = "stacked" if layout == "auto" else layout
        self.raw = raw
        self.verbose = verbose
        self.color = interactive if color is None else color
        self.width = max(width, 80)
        self.column = (self.width - 3) // 2
        self._lock = threading.Lock()
        self._header_done = False
        self._file = None
        if log_file is not None:
            try:
                log_file.parent.mkdir(parents=True, exist_ok=True)
                self._file = log_file.open("w", encoding="utf-8", buffering=1)
            except OSError:
                self._file = None

    def _paint(self, text: str, key: str) -> str:
        return f"{COLOR[key]}{text}{RESET}" if self.color and key in COLOR else text

    def _write(self, text: str) -> None:
        try:
            print(text, flush=True)
        except (UnicodeError, OSError):
            pass  # never let one unprintable line stop the log relay (the child would block on a full pipe)
        if self._file:
            try:
                self._file.write(ANSI.sub("", text) + "\n")
            except (OSError, ValueError):
                pass

    def _stacked(self, source: str, entry: Entry) -> None:
        text = entry.text if entry.severity == "info" else self._paint(entry.text, entry.severity)
        label = self._paint(f"{source:<8}", source)
        self._write(f"{self._paint(entry.time, 'dim')}  {label}  {text}")

    def header(self) -> None:
        if self.layout != "split" or self._header_done:
            return
        self._header_done = True
        left = "FRONTEND  web-search-ui :4301".ljust(self.column)
        right = "BACKEND  web-search-agent :8201"
        self._write(self._paint(left, "frontend") + " │ " + self._paint(right, "backend"))
        self._write("─" * self.column + "─┼─" + "─" * self.column)

    def run(self, message: str, severity: str = "info") -> None:
        """run.py's own messages."""
        with self._lock:
            self._stacked("run", Entry(severity, now(), message))

    def box(self, title: str, rows: list[tuple[str, str]], footer: str = "") -> None:
        """A framed block, e.g. the URLs once everything is up."""
        key_width = max((len(k) for k, _ in rows), default=0)
        body = [f"  {k:<{key_width}}  {v}" for k, v in rows]
        width = max([len(title) + 4, len(footer) + 2, *(len(b) for b in body)]) + 2
        with self._lock:
            self._write("")
            self._write(self._paint(f"┌─ {title} " + "─" * max(0, width - len(title) - 4), "ok"))
            for line in body:
                self._write(self._paint("│", "ok") + line)
            if footer:
                self._write(self._paint("│", "ok") + f"  {footer}")
            self._write(self._paint("└" + "─" * (width - 1), "ok"))
            self._write("")

    def line(self, source: str, raw_line: str) -> None:
        """A line of `frontend` or `backend` output."""
        if self.raw:
            entry: Entry | None = Entry("info", now(), ANSI.sub("", raw_line).rstrip())
        elif source == "backend":
            entry = format_backend(raw_line, self.verbose)
        else:
            entry = format_frontend(raw_line)
        if not entry or not entry.text.strip():
            return
        with self._lock:
            if self.layout == "stacked":
                self._stacked(source, entry)
                return
            self.header()
            text = f"{entry.time} {entry.text}"
            for part in textwrap.wrap(text, self.column, subsequent_indent="   ", drop_whitespace=False,
                                      replace_whitespace=False) or [""]:
                cell = part.ljust(self.column)
                cell = self._paint(cell, entry.severity) if entry.severity != "info" else cell
                blank = " " * self.column
                self._write(f"{cell} │ {blank}" if source == "frontend" else f"{blank} │ {cell}")

    def close(self) -> None:
        if self._file:
            self._file.close()
            self._file = None
