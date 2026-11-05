"""Black-box checks for the app: they talk HTTP to BENCH_BASE_URL and nothing else.

The accounts in accounts.json are made with the app's own `manage.py create_account`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import requests

HERE = Path(__file__).resolve().parent
BASE = os.environ.get("BENCH_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
PASSWORD = "bench-pass-123"
ACCOUNTS: dict[str, str] = json.loads((HERE / "accounts.json").read_text())


class Api:
    """A signed-in client: paths are relative to /api/."""

    def __init__(self, email: str) -> None:
        self.email = email
        self.session = requests.Session()
        reply = self.session.post(
            f"{BASE}/api/auth/login/", json={"email": email, "password": PASSWORD}, timeout=30
        )
        assert reply.status_code == 200, f"sign-in as {email}: {reply.status_code} {reply.text[:200]}"
        body = reply.json()
        token = body.get("access") or body.get("token")
        assert token, f"sign-in as {email}: no access or token in {list(body)}"
        self.session.headers["Authorization"] = f"Bearer {token}"

    def call(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        return self.session.request(method, f"{BASE}/api/{path.lstrip('/')}", timeout=30, **kwargs)

    def get(self, path: str, **kw: Any) -> requests.Response:
        return self.call("GET", path, **kw)

    def post(self, path: str, data: Any = None, **kw: Any) -> requests.Response:
        return self.call("POST", path, json=data if data is not None else {}, **kw)

    def patch(self, path: str, data: Any, **kw: Any) -> requests.Response:
        return self.call("PATCH", path, json=data, **kw)

    def delete(self, path: str, **kw: Any) -> requests.Response:
        return self.call("DELETE", path, **kw)


def rows(reply: requests.Response) -> list[dict[str, Any]]:
    """The items of a list reply: an array, or an object with a results array."""
    body = reply.json()
    if isinstance(body, dict) and "results" in body:
        body = body["results"]
    assert isinstance(body, list), f"not a list: {str(body)[:200]}"
    return body


def money(value: Any) -> Decimal:
    return Decimal(str(value))


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="session", autouse=True)
def accounts() -> None:
    project = Path(os.environ.get("BENCH_PROJECT", HERE.parent))
    python = os.environ.get("BENCH_PYTHON", sys.executable)
    for email, role in ACCOUNTS.items():
        done = subprocess.run(
            [python, "manage.py", "create_account", email, PASSWORD, role],
            cwd=project, capture_output=True, text=True, check=False,
        )  # fmt: skip
        assert done.returncode == 0, f"create_account {email} {role}: {done.stderr[-400:]}"


_apis: dict[str, Api] = {}


@pytest.fixture
def api() -> Any:
    """``api("staff")`` is a client signed in as the account with that key in accounts.json."""

    def sign_in(key: str) -> Api:
        email = next(e for e in ACCOUNTS if e.startswith(key + "@"))
        if email not in _apis:
            _apis[email] = Api(email)
        return _apis[email]

    return sign_in


@pytest.fixture
def anonymous() -> requests.Session:
    return requests.Session()

