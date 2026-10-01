"""Loaded by pytest before any agent's tests.

1. Tests never read the shared ``backend/.env`` (exactly like CI, where it doesn't exist): it may hold live keys,
   e.g. search API keys and the routes that send results to other machines on the network. ``ENV_FILE`` points
   ``utils.env`` at an empty file before any agent is imported. Set ``ENV_FILE`` yourself to test with a real file.
   ``WEB_SEARCH_*`` variables that still get in (e.g. from the shell) are removed for every test, including the
   orchestrator's end-to-end tests, which run the web search graph in-process.
2. The folder ``backend/web_search_agent`` has the same name as its package
   (``backend/web_search_agent/src/web_search_agent``). With ``--import-mode=importlib`` pytest imports a test file's
   parent folders by location, so collecting ``web_search_agent/tests`` would register the folder as an empty
   ``web_search_agent`` namespace package and hide the real one. Importing the real package first puts it in
   ``sys.modules`` and pytest reuses it.
3. Tests never read or write the supervisor's ``data/agent_overrides.yaml`` (planning text customised in the admin
   console on this machine): ``AGENT_OVERRIDES_FILE`` points at a temporary file for every test.
"""

import os

os.environ.setdefault("ENV_FILE", os.devnull)  # before utils.env runs (see 1.)

import pytest  # noqa: E402
from web_search_agent.settings import get_settings  # noqa: E402  also registers the real package (see 2.)


@pytest.fixture(autouse=True)
def _ignore_live_web_search_settings(monkeypatch):
    for key in [k for k in os.environ if k.startswith("WEB_SEARCH_")]:
        monkeypatch.delenv(key)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _own_agent_overrides_file(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_OVERRIDES_FILE", str(tmp_path / "agent_overrides.yaml"))  # see 3.
