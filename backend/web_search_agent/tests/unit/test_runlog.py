"""run.py's human-readable log (runlog.py, next to run.py - not part of the agent package)."""

import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("runlog", Path(__file__).resolve().parents[2] / "runlog.py")
runlog = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runlog)

LG = "api_variant=local_dev langgraph_api_version=0.15.1 thread_name=MainThread"


@pytest.mark.parametrize("line", [
    f"2026-09-28T10:45:31.644633Z [info     ] Worker stats                   [langgraph_api.metrics_collector] {LG}",
    f"2026-09-28T10:45:31.644633Z [info     ] Queue stats                    [langgraph_runtime_inmem.queue] {LG}",
    f"2026-09-28T10:45:31.644633Z [info     ] Resolved authentication handler [langgraph_api.auth.custom] {LG}",
    f'2026-09-28T10:45:31Z [info     ] HTTP Request: HEAD https://huggingface.co/BAAI/x "HTTP/1.1 200 OK" [httpx] {LG}',
    "INFO:langgraph_api.cli:",
    "",
])
def test_backend_noise_is_dropped(line):
    assert runlog.format_backend(line) is None


def test_backend_http_request_is_readable():
    line = (f'2026-09-28T10:45:31.644633Z [info     ] HTTP Request: POST http://192.168.1.33:8203/synthesize '
            f'"HTTP/1.1 200 OK" [httpx] {LG}')
    severity, text = runlog.format_backend(line)
    assert severity == "info"
    assert text.endswith("· POST http://192.168.1.33:8203/synthesize -> 200 OK  [httpx]")
    assert "api_variant" not in text and "langgraph_api_version" not in text
    assert text[2] == ":" and text[5] == ":"  # HH:MM:SS (local time)


def test_backend_run_lifecycle_is_short():
    done = (f"2026-09-28T10:23:17Z [info     ] Background run succeeded       [langgraph_api.worker] "
            f"graph_id=web_search run_exec_ms=24080 run_id=01a0 {LG}")
    assert runlog.format_backend(done)[1].endswith("· run finished in 24.1 s (web_search)  [worker]")


def test_warnings_and_errors_are_always_kept_and_marked():
    warn = f"2026-09-28T10:23:17Z [warning  ] Worker stats [langgraph_api.metrics_collector] {LG}"
    assert runlog.format_backend(warn)[0] == "warn"
    err = f"2026-09-28T10:23:17Z [error    ] output not sent: TargetNotFound: no machine [web_search_agent.x] {LG}"
    severity, text = runlog.format_backend(err)
    assert severity == "err" and "✗ output not sent" in text and text.endswith("[x]")


def test_other_backend_lines_pass_through():
    assert runlog.format_backend("║  ├─┤││││ ┬║ ╦├┬┘├─┤├─┘├─┤") == ("info", "║  ├─┤││││ ┬║ ╦├┬┘├─┤├─┘├─┤")
    assert runlog.format_backend("Traceback (most recent call last):")[0] == "err"


def test_frontend_lines():
    cached = "\x1b[32m INFO \x1b[0m Checksum of browser-tslib matched, re-using cached externals."
    assert runlog.format_frontend(cached) is None
    severity, text = runlog.format_frontend("Application bundle generation complete. [1.6 seconds]")
    assert severity == "info" and text.endswith("Application bundle generation complete. [1.6 seconds]")
    assert runlog.format_frontend("▲ [WARNING] pipeline-flow.css exceeded maximum budget.")[0] == "warn"
    assert runlog.format_frontend("✘ [ERROR] TS2339: Property 'x' does not exist")[0] == "err"


@pytest.mark.parametrize("line", [
    "main.js             | main          | 387 bytes |",
    "chunk-7NYJLY6U.js   | bootstrap     | 132.67 kB |",
    "Initial chunk files | Names         |  Raw size",
    "❯ Building...",
    "NOTE: Raw file sizes do not reflect development server per-request transformations.",
])
def test_frontend_build_tables_are_dropped(line):
    assert runlog.format_frontend(line) is None


def test_long_paths_are_shortened_and_a_known_harmless_warning_is_dropped():
    path = r"C:\Users\user\AppData\Local\Temp\venv\Lib\site-packages\langgraph\pregel\main.py:3230: UserWarning: x"
    assert runlog.format_backend(path) == ("info", r"…/site-packages/langgraph\pregel\main.py:3230: UserWarning: x")
    harmless = path.replace("x", "`durability` has no effect when no checkpointer is present.")
    assert runlog.format_backend(harmless) is None


def test_split_layout_puts_each_side_in_its_column(capsys):
    printer = runlog.Printer(layout="split", color=False)
    printer.width, printer.column = 81, 39
    printer.line("frontend", "Application bundle generation complete.")
    printer.line("backend", f"2026-09-28T10:23:17Z [info     ] run it [web_search_agent.api] {LG}")
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("FRONTEND") and "│ BACKEND" in lines[0]
    front = next(line for line in lines if "Application" in line)
    back = next(line for line in lines if "run it" in line)
    assert all(line.index("│") == 40 for line in lines[2:])  # every row keeps the column border
    assert "Application" in front.split("│")[0] and not front.split("│")[1].strip()
    assert "run it" in back.split("│")[1] and not back.split("│")[0].strip()


def test_stacked_layout_labels_each_line(capsys):
    printer = runlog.Printer(layout="stacked", color=False)
    printer.line("backend", f"2026-09-28T10:23:17Z [info     ] run it [web_search_agent.api] {LG}")
    assert capsys.readouterr().out.startswith("backend  │ ")
