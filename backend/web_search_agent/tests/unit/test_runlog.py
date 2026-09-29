"""run.py's human-readable log (runlog.py, next to run.py - not part of the agent package)."""

import importlib.util
import logging
import sys
from pathlib import Path

import pytest
from web_search_agent.steps import log_step

_spec = importlib.util.spec_from_file_location("runlog", Path(__file__).resolve().parents[2] / "runlog.py")
runlog = importlib.util.module_from_spec(_spec)
sys.modules["runlog"] = runlog  # @dataclass looks its module up there
_spec.loader.exec_module(runlog)

LG = "api_variant=local_dev langgraph_api_version=0.15.1 thread_name=MainThread"


def backend(message: str, source: str, level: str = "info") -> str:
    return f"2026-09-28T10:45:31.644633Z [{level:<9}] {message} [{source}] {LG}"


@pytest.mark.parametrize("line", [
    backend("Worker stats", "langgraph_api.metrics_collector"),
    backend("Queue stats", "langgraph_runtime_inmem.queue"),
    backend("Resolved authentication handler", "langgraph_api.auth.custom"),
    backend("Background run succeeded", "langgraph_api.worker"),  # the agent logs its own ■ Done line
    backend('HTTP Request: GET https://en.wikipedia.org/w/api.php?q=x "HTTP/1.1 200 OK"', "httpx"),
    "INFO:langgraph_api.cli:",
    "",
    # the startup banner (run.py prints its own box) and progress bars
    "╦  ┌─┐┌┐┌┌─┐╔═╗┬─┐┌─┐┌─┐┬ ┬",
    "- 🚀 API: http://127.0.0.1:8201",
    "This in-memory server is designed for development and testing.",
    "Loading weights: 100%|██████████| 105/105 [00:00<00:00, 4426.33it/s]",
])
def test_backend_noise_is_dropped(line):
    assert runlog.format_backend(line) is None


def test_backend_line_is_readable():
    entry = runlog.format_backend(backend("Output goes to http://192.168.1.30:8203/verify", "web_search_agent.x"))
    assert entry.severity == "info" and entry.text == "Output goes to http://192.168.1.30:8203/verify"
    assert entry.time[2] == ":" and entry.time[5] == ":"  # HH:MM:SS (local time)


def test_step_lines_are_indented_under_their_run():
    entry = runlog.format_backend(backend("✓ Query planner    3 queries (1.9 s)", "web_search_agent.steps"))
    assert entry.text == "  ✓ Query planner    3 queries (1.9 s)"


def test_http_requests_only_when_verbose_and_without_query_strings():
    line = backend('HTTP Request: GET https://en.wikipedia.org/w/api.php?srsearch=x "HTTP/1.1 200 OK"', "httpx")
    assert runlog.format_backend(line) is None
    assert runlog.format_backend(line, verbose=True).text == "GET https://en.wikipedia.org/w/api.php -> 200 OK  [httpx]"


def test_warnings_and_errors_are_always_kept_and_marked():
    warn = backend("Worker stats", "langgraph_api.metrics_collector", "warning")
    assert runlog.format_backend(warn).severity == "warn"
    err = runlog.format_backend(backend("✗ Send output  TargetNotFound", "web_search_agent.steps", "error"))
    assert err.severity == "err" and "✗ Send output" in err.text


def test_known_long_warnings_become_one_line():
    line = backend("Custom auth has no handler registered for some dispatch paths. Authentication ...",
                   "langgraph_api.auth.custom", "warning")
    entry = runlog.format_backend(line)
    assert entry.severity == "info" and entry.text.startswith("Custom auth: no resource-level handlers")
    tail = "    To get detailed profiling of slow operations, set FF_PROFILE_IMPORTS=true"
    assert runlog.format_backend(tail) is None


def test_tracebacks_pass_through_as_errors():
    assert runlog.format_backend("Traceback (most recent call last):").severity == "err"
    assert runlog.format_backend('  File "graph.py", line 3, in <module>').severity == "err"
    assert runlog.format_backend("ValueError: bad value").severity == "err"


def test_frontend_lines():
    cached = "\x1b[32m INFO \x1b[0m Checksum of browser-tslib matched, re-using cached externals."
    assert runlog.format_frontend(cached) is None
    built = runlog.format_frontend("Application bundle generation complete. [1.764 seconds] - 2026-09-29T05:57:50Z")
    assert built.severity == "ok" and built.text == "✓ UI built in 1.8 s"
    assert runlog.format_frontend("▲ [WARNING] pipeline-flow.css exceeded maximum budget.").severity == "warn"
    assert runlog.format_frontend("✘ [ERROR] TS2339: Property 'x' does not exist").severity == "err"


@pytest.mark.parametrize("line", [
    "main.js             | main          | 387 bytes |",
    "chunk-7NYJLY6U.js   | bootstrap     | 132.67 kB |",
    "Initial chunk files | Names         |  Raw size",
    "❯ Building...",
    "> frontend@0.0.0 start:web-search-ui",
    "[Federation SSE] Local reloader initialized with endpoint /@angular-architects/native-federation",
    "11:27:50 am [vite] (client) Re-optimizing dependencies because vite config has changed",
    "➜  Local:   http://localhost:4301/",
    "NOTE: Raw file sizes do not reflect development server per-request transformations.",
])
def test_frontend_noise_is_dropped(line):
    assert runlog.format_frontend(line) is None


def test_long_paths_are_shortened_and_a_known_harmless_warning_is_dropped():
    path = r"C:\Users\user\AppData\Local\Temp\venv\Lib\site-packages\langgraph\pregel\main.py:3230: UserWarning: x"
    assert runlog.format_backend(path).text == r"…/site-packages/langgraph\pregel\main.py:3230: UserWarning: x"
    harmless = path.replace("x", "`durability` has no effect when no checkpointer is present.")
    assert runlog.format_backend(harmless) is None


def test_printer_writes_a_plain_log_file(tmp_path, capsys):
    log_file = tmp_path / "logs" / "run.log"
    printer = runlog.Printer(color=True, log_file=log_file)
    printer.run("Starting backend")
    printer.line("backend", backend("▶ Search \"x\"", "web_search_agent.nodes.plan_queries"))
    printer.box("running", [("UI", "http://localhost:4301")])
    printer.close()
    shown = capsys.readouterr().out
    written = log_file.read_text(encoding="utf-8")
    assert "\033[" in shown and "\033[" not in written  # colours on screen only
    assert "run       Starting backend" in written and 'backend   ▶ Search "x"' in written
    assert "│  UI  http://localhost:4301" in written


def test_steps_log_one_readable_line(caplog):
    caplog.set_level(logging.INFO, logger="web_search_agent.steps")
    log_step({"id": "plan", "title": "Query planner", "status": "done", "detail": "2 queries", "duration_s": 1.94,
              "items": ["a", "b"]})
    log_step({"id": "extract", "title": "Fetch & extract", "status": "done", "detail": "4/4 pages", "duration_s": 7.8,
              "items": ["ok  en.wikipedia.org"]})
    log_step({"id": "verify", "title": "Send output", "status": "failed", "detail": "not found", "duration_s": None,
              "items": []})
    log_step({"id": "search", "title": "Web search", "status": "running", "detail": "", "items": []})
    lines = [(r.levelname, r.getMessage()) for r in caplog.records]
    assert lines == [
        ("INFO", "✓ Query planner    2 queries (1.9 s): a | b"),
        ("INFO", "✓ Fetch & extract  4/4 pages (7.8 s)"),  # items repeat the detail: not shown
        ("WARNING", "✗ Send output      not found"),
    ]  # running steps are not logged
