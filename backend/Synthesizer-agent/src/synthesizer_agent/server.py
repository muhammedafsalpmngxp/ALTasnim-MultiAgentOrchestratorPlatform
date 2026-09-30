"""The synthesizer's HTTP routes when it runs as a LangGraph deployment (langgraph.json).

The app of api.py without its two catch-all routes (any path), which would hide the LangGraph API (/threads,
/assistants, ...). Standalone (run.py) serves api.py unchanged, catch-alls included.
"""

from synthesizer_agent.api import app

app.router.routes = [route for route in app.router.routes if getattr(route, "path", None) != "/{path:path}"]
