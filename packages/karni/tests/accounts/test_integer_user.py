"""Karni's accounts flows work with a project's integer-keyed user model.

``AUTH_USER_MODEL`` cannot change inside one test process, so this runs
``tests/intuserapp/`` (login, JWT, ``me/``, roles, the 2FA gate, sign-in with
an ID token or a code, the terms gate, per-user grants) in a subprocess with
``KARNI_TEST_USER_PK=bigint``, on the same database engine and settings module
as this run. On PostgreSQL the subprocess gets its own test database.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]  # packages/karni


def test_the_accounts_flows_with_an_integer_keyed_user(request: pytest.FixtureRequest) -> None:
    env = {**os.environ, "KARNI_TEST_USER_PK": "bigint"}
    url = env.get("DATABASE_URL", "")
    if url.startswith("postgres"):
        env["DATABASE_URL"] = url.rstrip("/") + "_intuser"  # never the parent's test database
    args = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/intuserapp"]
    if os.environ.get("DJANGO_SETTINGS_MODULE"):
        args.append(f"--ds={os.environ['DJANGO_SETTINGS_MODULE']}")
    if request.config.getoption("nomigrations", default=False):
        args.append("--no-migrations")
    result = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
    summary = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert " passed" in summary, summary  # the 2FA flow skips without karni[2fa]
