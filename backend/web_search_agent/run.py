#!/usr/bin/env python
"""Run only the web-search part in one terminal: backend agent (:8201) + its micro-frontend web-search-ui (:4301).

    cd backend/web_search_agent
    python run.py                  # both; the backend restarts when its code, prompts or .env change
    python run.py --backend-only
    python run.py --frontend-only
    python run.py --no-reload      # don't restart the backend on file changes
    python run.py --host 0.0.0.0   # backend reachable from other machines (default: this machine only)
    python run.py --install        # first run: pip install -r requirements.txt + npm install
    python run.py --verbose        # also every HTTP request the backend makes (search APIs, pages, output)
    python run.py --layout split   # frontend | backend in two columns instead of one labelled stream
    python run.py --raw            # the original, unfiltered log lines

Use the Python environment you installed requirements.txt into (3.11 - 3.13). Ctrl+C stops both.
If the frontend exits, everything stops; if the backend crashes, it waits for a fix and restarts.
Nothing of the other agents is started; ports 8201 / 4301 are checked before anything runs.
Settings come from this folder's .env. The log is also written, without colours, to logs/run.log (new every start).
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from runlog import Printer

AGENT_DIR = Path(__file__).resolve().parent  # backend/web_search_agent
BACKEND_DIR = AGENT_DIR.parent  # backend
REPO_DIR = BACKEND_DIR.parent
FRONTEND_DIR = REPO_DIR / "frontend"
UI_PROJECT = "web-search-ui"  # the Angular project name (angular.json, `npm run start:web-search-ui`)
UI_DIR = FRONTEND_DIR / "agents" / "web_search_ui"
BACKEND_PORT = 8201  # the platform's port for web-search-agent
FRONTEND_PORT = 4301  # angular.json -> web-search-ui -> serve-original.options.port
LOG_FILE = AGENT_DIR / "logs" / "run.log"  # git-ignored
IS_WINDOWS = os.name == "nt"

printer = Printer()  # replaced in main() once --layout / --raw / --verbose are known (runlog.py)


def log(name: str, message: str, severity: str = "info") -> None:
    """run.py's own messages (name "run") or a line of frontend / backend output."""
    if name == "run":
        printer.run(message, severity)
    else:
        printer.line(name, message)


def fail(message: str) -> None:
    log("run", message, "err")
    sys.exit(1)


def port_in_use(port: int) -> bool:
    # IPv4 and IPv6: Node's dev server often listens on ::1 only.
    for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.5)
                if sock.connect_ex((host, port)) == 0:
                    return True
        except OSError:
            continue
    return False


# --- checks / setup ----------------------------------------------------------------
def npm_executable() -> str:
    npm = shutil.which("npm")
    if not npm:
        fail("npm not found. Install Node.js 20+ (https://nodejs.org) and try again.")
    return npm


def ensure_backend(install: bool) -> None:
    if not (3, 11) <= sys.version_info[:2] <= (3, 13):
        fail(f"Python {sys.version.split()[0]} is not supported: the LangGraph server needs 3.11 - 3.13. "
             "Activate your conda env / venv first, e.g. `conda activate <your-env>`.")
    missing = [m for m in ("langgraph_cli", "langgraph_api", "web_search_agent", "utils", "trafilatura")
               if importlib.util.find_spec(m) is None]
    if not missing:
        return
    if not install:
        fail(f"Missing in this Python ({sys.executable}): {', '.join(missing)}.\n"
             f"           Install once:  python run.py --install   (or: pip install -r requirements.txt)")
    log("run", "Installing the backend requirements (requirements.txt)...")
    subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], cwd=AGENT_DIR, check=True)


def ensure_frontend(install: bool) -> None:
    if not UI_DIR.is_dir():
        fail(f"{UI_DIR} not found.")
    if (FRONTEND_DIR / "node_modules").is_dir():
        return
    if not install:
        fail("frontend/node_modules not found. Install once:  python run.py --install   (or: cd frontend; npm install)")
    log("run", "Installing the frontend packages (npm install)...")
    subprocess.run([npm_executable(), "install"], cwd=FRONTEND_DIR, check=True)


def check_env_file() -> None:
    env_file = AGENT_DIR / ".env"
    if env_file.is_file():
        log("run", "Settings: backend/web_search_agent/.env")
    else:
        log("run", "No backend/web_search_agent/.env - running with defaults (offline sample data). "
                   "Create it:  copy .env.example .env", "warn")


# --- processes ----------------------------------------------------------------------
class Service:
    def __init__(self, name: str, command: list[str], cwd: Path, env: dict[str, str] | None = None,
                 summary: str = ""):
        self.name = name
        self.summary = summary or " ".join(command)
        self.command = command
        self.cwd = cwd
        self.env = env or {}
        self.process: subprocess.Popen | None = None

    def start(self) -> None:
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", **self.env}
        self.process = subprocess.Popen(
            self.command,
            cwd=self.cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            # Own process group: Ctrl+C in this console reaches only run.py, which then stops the whole tree.
            **({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if IS_WINDOWS else {"start_new_session": True}),
        )
        threading.Thread(target=self._pipe_output, args=(self.process,), daemon=True).start()

    def _pipe_output(self, process: subprocess.Popen) -> None:
        assert process.stdout
        for line in process.stdout:
            line = line.rstrip()
            if line:
                log(self.name, line)

    def restart(self) -> None:
        self.stop()
        self.start()

    def poll(self) -> int | None:
        return self.process.poll() if self.process else None

    def stop(self) -> None:
        if not self.process or self.process.poll() is not None:
            return
        log("run", f"Stopping {self.name}...")
        if IS_WINDOWS:
            subprocess.run(["taskkill", "/PID", str(self.process.pid), "/T", "/F"], capture_output=True)
        else:
            import signal

            try:
                os.killpg(self.process.pid, signal.SIGTERM)
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


class FileWatcher:
    """Polls modification times. Replaces the server's own reload, whose Windows restart mechanism
    (a console-wide Ctrl+C) is unreliable when the server runs as a child process with piped output."""

    def __init__(self, dirs: list[Path], patterns: list[str], files: list[Path]):
        self.dirs = dirs
        self.patterns = patterns
        self.files = files
        self._mtimes = self._scan()

    def _scan(self) -> dict[Path, float]:
        paths = [p for d in self.dirs for pattern in self.patterns for p in d.rglob(pattern)
                 if "__pycache__" not in p.parts]
        paths += [p for p in self.files if p.exists()]
        mtimes = {}
        for path in paths:
            try:
                mtimes[path] = path.stat().st_mtime
            except OSError:
                pass  # deleted between listing and stat
        return mtimes

    def changed(self) -> list[Path]:
        current = self._scan()
        changed = [p for p, mtime in current.items() if self._mtimes.get(p) != mtime]
        changed += [p for p in self._mtimes if p not in current]
        self._mtimes = current
        return changed


def announce_when_ready(host: str, with_backend: bool, with_frontend: bool, services: list[Service]) -> None:
    """Print the URLs once everything answers."""
    deadline = time.time() + 300
    backend_ok, frontend_ok = not with_backend, not with_frontend
    while time.time() < deadline and not (backend_ok and frontend_ok):
        if any(s.poll() is not None for s in services):
            return
        if not backend_ok:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{BACKEND_PORT}/ok", timeout=2)
                backend_ok = True
            except OSError:
                pass
        if not frontend_ok:
            frontend_ok = port_in_use(FRONTEND_PORT)
        time.sleep(1)

    rows: list[tuple[str, str]] = []
    if with_frontend:
        rows += [("UI", f"http://localhost:{FRONTEND_PORT}")]
    if with_backend:
        rows += [
            ("Agent API", f"http://127.0.0.1:{BACKEND_PORT}   (graph: web_search)"),
            ("Health", f"http://127.0.0.1:{BACKEND_PORT}/custom/health"),
            ("Card", f"http://127.0.0.1:{BACKEND_PORT}/card"),
            ("Studio", f"https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:{BACKEND_PORT}"),
        ]
        if host == "0.0.0.0":
            rows += [("Other machines", f"http://<this-machine-ip>:{BACKEND_PORT}")]
    rows += [("Log file", str(LOG_FILE.relative_to(REPO_DIR)))]
    printer.box("web-search-agent is running", rows, "Ctrl+C stops everything.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--backend-only", action="store_true", help="start only the web-search-agent (:8201)")
    group.add_argument("--frontend-only", action="store_true", help="start only web-search-ui (:4301)")
    parser.add_argument("--no-reload", action="store_true", help="don't restart the backend when its files change")
    parser.add_argument("--host", default="127.0.0.1", help="backend host; 0.0.0.0 = reachable from the network")
    parser.add_argument("--install", action="store_true", help="install missing backend / frontend dependencies")
    parser.add_argument("--layout", choices=("auto", "split", "stacked"), default="auto",
                        help="log layout: one labelled stream (stacked, default) or frontend | backend columns (split)")
    parser.add_argument("--verbose", action="store_true", help="also log every HTTP request of the backend")
    parser.add_argument("--raw", action="store_true", help="show the original log lines, unfiltered")
    args = parser.parse_args()

    # The children's logs contain box-drawing / arrow characters; a cp1252 console or pipe cannot encode them.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    if IS_WINDOWS:
        os.system("")  # enables ANSI colours in the Windows console
    global printer
    printer = Printer(args.layout, args.raw, verbose=args.verbose, log_file=LOG_FILE)

    with_backend = not args.frontend_only
    with_frontend = not args.backend_only

    # Refuse to start into a port that is taken, instead of half-starting.
    if with_backend and port_in_use(BACKEND_PORT):
        fail(f"Port {BACKEND_PORT} is already in use - is web-search-agent (or docker compose) already running?")
    if with_frontend and port_in_use(FRONTEND_PORT):
        fail(f"Port {FRONTEND_PORT} is already in use - is web-search-ui (or `npm start` of the platform) running?")

    services: list[Service] = []
    backend: Service | None = None
    watcher: FileWatcher | None = None
    if with_backend:
        ensure_backend(args.install)
        check_env_file()
        # --no-reload: run.py does the reloading (see FileWatcher). Same Python as run.py -> same environment.
        command = [sys.executable, "-m", "langgraph_cli", "dev", "--port", str(BACKEND_PORT), "--host", args.host,
                   "--no-browser", "--no-reload"]
        backend = Service("backend", command, AGENT_DIR, summary=f"langgraph dev on {args.host}:{BACKEND_PORT}")
        services.append(backend)
        if not args.no_reload:
            watcher = FileWatcher(
                [AGENT_DIR / "src", BACKEND_DIR / "utils"], ["*.py", "*.md"],
                [AGENT_DIR / ".env", BACKEND_DIR / ".env", AGENT_DIR / "langgraph.json"],
            )
    if with_frontend:
        ensure_frontend(args.install)
        # ng serve reloads itself on changes.
        services.append(Service("frontend", [npm_executable(), "run", f"start:{UI_PROJECT}"], FRONTEND_DIR,
                                summary=f"ng serve {UI_PROJECT} on :{FRONTEND_PORT}"))

    for service in services:
        log("run", f"Starting {service.name} ({service.summary})")
        service.start()
    if watcher:
        log("run", "The backend restarts when src/, backend/utils, the .env files or langgraph.json change.")
    threading.Thread(target=announce_when_ready, args=(args.host, with_backend, with_frontend, services),
                     daemon=True).start()

    exit_code = 0
    backend_crashed = False
    try:
        while True:
            time.sleep(0.5)
            if watcher and backend and (changed := watcher.changed()):
                time.sleep(0.3)  # let editors finish writing (save-all, formatters)
                watcher.changed()
                names = ", ".join(p.name for p in changed[:3])
                log("run", f"Change detected in {names} - restarting backend...")
                backend.restart()
                backend_crashed = False
            for service in services:
                code = service.poll()
                if code is None:
                    continue
                if service is backend and watcher:
                    # e.g. a syntax error in the file just saved: keep the frontend up and wait for a fix.
                    if not backend_crashed:
                        log("run", f"backend exited with code {code}; waiting for a file change to restart it.", "err")
                        backend_crashed = True
                    continue
                log("run", f"{service.name} exited with code {code}; shutting down.", "err")
                exit_code = code or 1
                raise SystemExit
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        for service in services:
            service.stop()
        log("run", "Stopped.")
        printer.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
