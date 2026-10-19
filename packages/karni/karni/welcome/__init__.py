"""The welcome page: what a developer sees at ``/`` on first boot, generated live.

Mounted last in a project's URLconf::

    from karni.welcome import welcome_urls

    urlpatterns = [
        ...,
        *welcome_urls(),   # only while DEBUG is on; the first project route for "/" wins
    ]

:func:`welcome_urls` returns the route only when ``DEBUG`` is true, so a
production URLconf never carries it; the view itself answers 404 with
``DEBUG`` off, and the system check ``karni.E505`` fails the boot if the
route is reachable anyway. Because the route is last, the moment the project
defines its own ``""`` path the page is gone — nothing to flip or delete.

The page is one self-contained HTML response (inline CSS and SVG, no build
step, no CDN, no network) built from introspection at request time:
the project's models with their admin and API links, the installed modules,
seven status checks each with the exact command that fixes it, the live
``karni context`` output and the first prompt to hand an agent. It shows the
presence or absence of configuration, never a value.
"""

from __future__ import annotations

from typing import Any

__all__ = ["media_urls", "welcome_urls"]


def media_urls() -> list[Any]:
    """Serve ``MEDIA_URL`` from ``MEDIA_ROOT`` while ``DEBUG`` is on and storage is local.

    ``karni serve --local`` has no proxy in front of Django, so without this
    every upload, admin image preview and file link is a 404 in development.
    Returns ``[]`` with ``DEBUG`` off or ``KARNI_STORAGE=s3`` (the bucket
    serves its own files). Mount it like :func:`welcome_urls`::

        urlpatterns = [..., *media_urls(), *welcome_urls()]
    """
    from django.conf import settings
    from django.conf.urls.static import static

    if not settings.DEBUG:
        return []
    backend = str(getattr(settings, "STORAGES", {}).get("default", {}).get("BACKEND", ""))
    if backend != "django.core.files.storage.FileSystemStorage":
        return []
    return list(static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT))


def welcome_urls() -> list[Any]:
    """``[path("", WelcomeView)]`` while ``DEBUG`` is on, else ``[]``."""
    from django.conf import settings
    from django.urls import path

    if not settings.DEBUG:
        return []
    from karni.welcome.views import WelcomeView

    return [path("", WelcomeView.as_view(), name="karni-welcome")]
