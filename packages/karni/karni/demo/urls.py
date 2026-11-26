"""Demo mode's routes.

* ``urlpatterns`` (``path("api/demo/", include("karni.demo.urls"))``): ``GET /api/demo/``.
* :func:`app_urls`: the React app's routes, ``/`` and every path Django does not answer
  itself. Put ``*app_urls()`` last in the project's ``urlpatterns``. The first segments
  in :func:`reserved` stay Django's (or WhiteNoise's), so an unknown API path answers
  404, not the app's page, and ``/admin`` without its slash is redirected as usual.

Override / escape hatch: ``KARNI_DEMO_APP_RESERVED`` adds first segments to :func:`reserved`
(for example ``"payments"``), and you can write your own pattern for :func:`karni.demo.views.app`.
"""

from __future__ import annotations

import re

from django.conf import settings
from django.urls import URLPattern, path, re_path

from karni.demo import views

__all__ = ["app_urls", "reserved", "urlpatterns"]

urlpatterns = [path("", views.DemoInfoView.as_view(), name="karni-demo")]


def reserved() -> list[str]:
    """The first path segments the app's page never answers."""
    names = [
        "api",
        "health",
        "healthz",
        "readyz",
        "assets",
        getattr(settings, "KARNI_ADMIN_PATH", "admin/"),
        getattr(settings, "STATIC_URL", "static/"),
        getattr(settings, "MEDIA_URL", "media/"),
        *getattr(settings, "KARNI_DEMO_APP_RESERVED", ()),
    ]
    found = [segment for name in names if (segment := str(name).strip("/"))]
    return list(dict.fromkeys(found))


def app_urls() -> list[URLPattern]:
    """One pattern: any path whose first segment is not :func:`reserved` renders the app."""
    skipped = "|".join(re.escape(segment) for segment in reserved())
    return [re_path(rf"^(?!(?:{skipped})(?:/|$))(?P<path>.*)$", views.app, name="karni-demo-app")]
