"""Start the synthesizer agent with the host and port from backend/.env.

    .venv\\Scripts\\python run.py

    SYNTHESIZER_HOST=0.0.0.0     # 0.0.0.0 = reachable from other computers
    SYNTHESIZER_PORT=8203        # the port other agents send to
    SYNTHESIZER_RELOAD=true      # restart automatically when code changes (dev)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import uvicorn

SRC = Path(__file__).resolve().parent / "src"
sys.path.insert(0, str(SRC))

from synthesizer_agent import agent  # noqa: E402  (importing it loads backend/.env)


def settings() -> dict:
    return {
        "host": os.getenv("SYNTHESIZER_HOST", "0.0.0.0"),
        "port": int(os.getenv("SYNTHESIZER_PORT", "8203")),
        "reload": os.getenv("SYNTHESIZER_RELOAD", "true").lower() in ("1", "true", "yes"),
    }


if __name__ == "__main__":
    s = settings()
    print(f"Synthesizer agent on http://{s['host']}:{s['port']}  (LLM: {agent.llm_info() or 'none configured'})")
    uvicorn.run("synthesizer_agent.api:app", app_dir=str(SRC), **s)
