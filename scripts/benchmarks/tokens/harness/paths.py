"""Where the harness keeps things. Everything outside the repository lives under one folder."""

from __future__ import annotations

import os
from pathlib import Path

TOKENS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TOKENS_DIR.parents[2]
TASKS_DIR = TOKENS_DIR / "tasks"
REFERENCE_DIR = TOKENS_DIR / "reference"

DEFAULT_HOME = Path.home() / ".cache" / "karni-dev" / "bench"
PORT_RANGE = range(8700, 8800)  # never 8000, 8765, 5173 or 8431
DATABASE_HOST = "127.0.0.1"
DATABASE_PORT = 55432
DATABASE_USER = "postgres"


def home() -> Path:
    """The folder for runs and the cached starting projects (KARNI_BENCH_HOME overrides it)."""
    return Path(os.environ.get("KARNI_BENCH_HOME", str(DEFAULT_HOME)))


def database_url(name: str) -> str:
    return f"postgres://{DATABASE_USER}@{DATABASE_HOST}:{DATABASE_PORT}/{name}"
