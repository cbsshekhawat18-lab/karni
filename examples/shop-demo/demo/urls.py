"""The React app's routes: ``/`` and every path Django does not answer itself.

``config/urls.py`` puts them last. The paths below stay Django's (or WhiteNoise's),
so an unknown API path answers 404, not the app's page.
"""

from __future__ import annotations

import re

from django.conf import settings
from django.urls import URLPattern, re_path

from demo import views


def reserved() -> list[str]:
    """Path prefixes the app's page never answers."""
    static = str(settings.STATIC_URL).strip("/")
    media = str(settings.MEDIA_URL).strip("/")
    names = [
        "api/",
        "health/",
        "healthz",
        "readyz",
        "payments/",
        "assets/",
        settings.KARNI_ADMIN_PATH,
    ]
    return [*names, *(f"{prefix}/" for prefix in (static, media) if prefix)]


def app_urls() -> list[URLPattern]:
    """One pattern: any path outside :func:`reserved` renders the app."""
    skipped = "|".join(re.escape(prefix) for prefix in reserved())
    return [re_path(rf"^(?!{skipped})(?P<path>.*)$", views.app, name="demo-app")]
