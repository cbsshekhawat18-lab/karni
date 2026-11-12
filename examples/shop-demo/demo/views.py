"""The built React app at ``/``, served by Django: one service, no Caddy in front.

WhiteNoise serves the build's files (``/assets/...``, ``WHITENOISE_ROOT``) and
the collected static files. Every other path that is not Django's (the API,
the admin, the health checks) answers the app's ``index.html``, so a reload or
a shared link of a deeper page works.

While ``DEMO_MODE`` is on, the page carries the demo login in meta tags,
which the sign-in prompt shows (``frontend/src/demo.tsx``)::

    <meta name="demo-login-email" content="demo@example.com">
    <meta name="demo-login-password" content="karni-password">
    <meta name="demo-reset-hours" content="24">
    <meta name="demo-admin-url" content="/admin/">
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.urls import reverse
from django.utils.html import escape

from demo import account

NOT_BUILT = (
    "<!doctype html><title>Shop Demo</title><h1>The React app is not built</h1>"
    "<p>Run <code>npm run build</code> in <code>frontend/</code>, or use its dev server.</p>"
)


def index_path() -> Path:
    """The built ``index.html`` (``DEMO_APP_INDEX``)."""
    return Path(settings.DEMO_APP_INDEX)


def notice() -> str:
    """The meta tags with the demo login, or ``""`` while ``DEMO_MODE`` is off."""
    if not account.demo_mode():
        return ""
    values = {
        "demo-login-email": account.email(),
        "demo-login-password": account.password(),
        "demo-reset-hours": str(account.reset_hours()),
        "demo-admin-url": reverse("admin:index"),
    }
    return "".join(
        f'<meta name="{name}" content="{escape(value)}">' for name, value in values.items()
    )


def app(request: HttpRequest, path: str = "") -> HttpResponse:
    """The app's page, for ``/`` and every deeper path of the app."""
    try:
        html = index_path().read_text(encoding="utf-8")
    except OSError:
        return HttpResponse(NOT_BUILT, status=503)
    html = html.replace("</head>", f"{notice()}</head>", 1)
    response = HttpResponse(html)
    response["Cache-Control"] = "no-cache"  # a new build's scripts on the next visit
    return response
