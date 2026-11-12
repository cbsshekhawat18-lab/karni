"""The React app's routes: ``/`` and every path Django does not answer itself.

``config/urls.py`` puts them last. The paths below stay Django's (or WhiteNoise's),
so an unknown API path answers 404, not the app's page, and ``/admin`` without
its slash is redirected to the admin as usual.
"""

from __future__ import annotations

import re

from django.conf import settings
from django.urls import URLPattern, re_path

from demo import views


def reserved() -> list[str]:
    """The first path segments the app's page never answers."""
    names = [
        "api",
        "health",
        "healthz",
        "readyz",
        "payments",
        "assets",
        settings.KARNI_ADMIN_PATH,
        settings.STATIC_URL,
        settings.MEDIA_URL,
    ]
    return [segment for name in names if (segment := str(name).strip("/"))]


def app_urls() -> list[URLPattern]:
    """One pattern: any path whose first segments are not :func:`reserved` renders the app."""
    skipped = "|".join(re.escape(segment) for segment in reserved())
    return [re_path(rf"^(?!(?:{skipped})(?:/|$))(?P<path>.*)$", views.app, name="demo-app")]
