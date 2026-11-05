"""Sign-in with an ID token next to django-allauth's redirect flow, in session mode.

allauth's provider pages live under the same ``social/`` prefix, one level
deeper (``social/google/login/``) or on fixed names (``social/signup/``).
Karni declares its ``social/<provider>/`` routes first, so both resolve. The
project boots in a subprocess because allauth's apps must be installed when
Django starts.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("cryptography", reason="sign-in with an ID token needs karni[social-token]")
pytest.importorskip("allauth", reason="the allauth flow needs karni[social]")

PACKAGE_ROOT = Path(__file__).resolve().parents[2]

SCRIPT = """
import json

import django

django.setup()

from django.core.management import call_command
from django.test import Client
from django.urls import resolve

from tests.accounts import idtokens

call_command("migrate", verbosity=0)
idtokens.reset()
out = {
    "token_view": resolve("/api/auth/social/google/").func.view_class.__name__,
    "allauth_login": resolve("/api/auth/social/google/login/").func.__module__,
    "allauth_callback": resolve("/api/auth/social/google/login/callback/").func.__module__,
    "allauth_signup": resolve("/api/auth/social/signup/").func.__module__,
    "allauth_connections": resolve("/api/auth/social/").func.__module__,
}
client = Client()
out["allauth_status"] = client.get("/api/auth/social/google/login/").status_code
response = client.post(
    "/api/auth/social/google/",
    {"id_token": idtokens.mint("google")},
    content_type="application/json",
)
out["token_status"] = response.status_code
out["token_user"] = response.json().get("user", {}).get("email")
out["me"] = client.get("/api/auth/me/").json().get("email")
print("RESULT " + json.dumps(out))
"""


def test_id_tokens_and_allauth_routes_work_together_in_session_mode() -> None:
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "tests.accounts.allauth_session.settings",
        "PYTHONPATH": str(PACKAGE_ROOT),
    }
    for var in ("DJANGO_ENV", "SENTRY_DSN", "DATABASE_URL", "KARNI_AUTH_MODE"):
        env.pop(var, None)
    completed = subprocess.run(
        [sys.executable, "-c", SCRIPT],
        cwd=PACKAGE_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr[-4000:]
    line = next(row for row in completed.stdout.splitlines() if row.startswith("RESULT "))
    out = json.loads(line.removeprefix("RESULT "))
    assert out["token_view"] == "SocialTokenLoginView"
    for key in ("allauth_login", "allauth_callback", "allauth_signup", "allauth_connections"):
        assert out[key].startswith("allauth."), (key, out[key])
    assert out["allauth_status"] == 200  # allauth's own confirmation page
    assert out["token_status"] == 200
    assert out["token_user"] == out["me"] == "ada@example.com"
