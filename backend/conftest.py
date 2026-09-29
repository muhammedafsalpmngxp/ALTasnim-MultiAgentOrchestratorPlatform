"""Loaded by pytest before any agent's tests.

The folder ``backend/web_search_agent`` has the same name as its package (``backend/web_search_agent/src/web_search_agent``).
With ``--import-mode=importlib`` pytest imports a test file's parent folders by location, so collecting
``web_search_agent/tests`` would register the folder as an empty ``web_search_agent`` namespace package and hide the
real one. Importing the real package first puts it in ``sys.modules`` and pytest reuses it.
"""

import web_search_agent  # noqa: F401
