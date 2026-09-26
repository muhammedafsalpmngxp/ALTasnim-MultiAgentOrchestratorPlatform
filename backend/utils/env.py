"""Loads the single ``backend/.env`` for every agent.

Real environment variables always win (``override=False``), so Docker
(``env_file``), CI and production secrets take precedence over the file.
Set ``ENV_FILE`` to use a different file.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# backend/utils/env.py -> parents[1] == backend/
BACKEND_ROOT = Path(__file__).resolve().parents[1]


def load_env() -> None:
    env_file = Path(os.getenv("ENV_FILE", BACKEND_ROOT / ".env"))
    if env_file.is_file():
        load_dotenv(env_file, override=False)
