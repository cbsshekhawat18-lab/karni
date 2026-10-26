"""The site's pages and the models with pages of their own: what the admin offers to link to.

:func:`site_pages` lists every named URL that takes no argument, except the
admin's, the API's and the static files' own (the addresses a redirect may
not start from either). :func:`linkable_models` lists the installed models
whose rows have a page (``get_absolute_url``), for a menu item that points
at a row or lists a model's rows.

Override / escape hatch: a menu item or page SEO entry written in code (or
with ``karni load``) may name any URL name; these lists only fill the
admin's choices.
"""

from __future__ import annotations

from typing import Any

from django.apps import apps
from django.urls import NoReverseMatch, reverse

__all__ = ["linkable_models", "site_pages"]

#: Apps whose models are framework machinery, never a page a client links to.
_INTERNAL_APPS = frozenset(
    {
        "admin",
        "auth",
        "contenttypes",
        "sessions",
        "sites",
        "karni_site",
        "karni_accounts",
        "karni_audit",
        "token_blacklist",
        "django_celery_beat",
        "django_celery_results",
    }
)


def site_pages() -> list[tuple[str, str]]:
    """``(URL name, path)`` for every page a link can name without arguments."""
    from karni_site.checks import url_names
    from karni_site.redirects import _protected_prefixes

    excluded = (*_protected_prefixes(), "/health")
    found: dict[str, str] = {}
    for name in url_names():
        if name in found or name.split(":", 1)[0] in ("admin", "karni"):
            continue
        try:
            path = reverse(name)
        except NoReverseMatch:
            continue
        if path.startswith(excluded):
            continue
        found[name] = path
    return sorted(found.items(), key=lambda item: (item[1], item[0]))


def linkable_models() -> list[type[Any]]:
    """Installed models whose rows have a page of their own (``get_absolute_url``)."""
    return [
        model
        for model in apps.get_models()
        if hasattr(model, "get_absolute_url") and model._meta.app_label not in _INTERNAL_APPS
    ]
