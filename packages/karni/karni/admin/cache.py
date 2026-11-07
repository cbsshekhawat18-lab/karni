"""The admin's *API cache* screen: see how response caching is set up, and clear it.

It shows whether ``KARNI_API_CACHE`` is on, the cache backend and alias in
use, how clearing works with that backend (``delete_pattern`` or version
tokens), the daily flush ``KARNI_API_CACHE_FLUSH`` schedules, and every
routed resource with its TTL and the models it reads. Two buttons: *Clear
everything*, and *Clear* on one resource (:func:`karni.api.caching.clear`).

It lives at ``<admin>/karni/api-cache/`` and the admin index lists it under
*Karni*. :class:`KarniAdminConfig <karni.admin.apps.KarniAdminConfig>`
installs it on the ``KARNI_ADMIN_SITE`` at startup. Only superusers see it,
since a clear affects every user of the API.

Override / escape hatch: subclass :class:`ApiCacheScreen` (for example
:meth:`~ApiCacheScreen.has_permission`, to let a role in) and call
``install(site, screen=MyScreen)`` from an ``admin.py``. A later install
replaces the screen. The template is ``karni_admin/api_cache.html``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.translation import gettext as _

__all__ = ["ApiCacheScreen", "CachedResource", "install"]

#: The screen's path under the admin, and its URL name in the admin's namespace.
SCREEN_PATH: Final = "karni/api-cache/"
URL_NAME: Final = "karni_api_cache"
_INSTALLED: Final = "_karni_api_cache_screen"


@dataclass(frozen=True)
class CachedResource:
    """One routed resource as the screen lists it."""

    route: str
    viewset: str
    model: str
    cached: bool
    ttl: int | None
    note: str
    reads: tuple[str, ...]


class ApiCacheScreen:
    """The view behind the screen. One instance per admin site."""

    template_name = "karni_admin/api_cache.html"

    def __init__(self, site: Any) -> None:
        self.site = site

    def has_permission(self, request: HttpRequest) -> bool:
        """Who may see and use the screen: active superusers."""
        user = getattr(request, "user", None)
        return bool(getattr(user, "is_active", False) and getattr(user, "is_superuser", False))

    def resources(self) -> list[CachedResource]:
        """Every routed ``BaseViewSet``, with how it is cached and the models it reads."""
        from karni.api.caching import Cache, Uncached, default_ttl, dependencies
        from karni.api.routers import resolve_router
        from karni.api.viewsets import BaseViewSet

        found: list[CachedResource] = []
        seen: set[type[Any]] = set()
        for prefix, viewset, _basename in getattr(resolve_router(), "registry", ()):
            if viewset in seen or not (
                isinstance(viewset, type) and issubclass(viewset, BaseViewSet)
            ):
                continue
            seen.add(viewset)
            model = viewset.model or getattr(viewset.queryset, "model", None)
            if model is None:
                continue
            declared = getattr(viewset, "cache", None)
            uncached = isinstance(declared, Uncached)
            ttl = None if uncached else (getattr(declared, "ttl", None) or default_ttl())
            if isinstance(declared, Uncached):
                note = _("never cached: %(reason)s") % {"reason": declared.reason}
            elif isinstance(declared, Cache) and declared.ttl:
                note = _("ttl set on the viewset")
            else:
                note = ""
            reads = tuple(sorted(m._meta.label for m in dependencies(viewset)))
            found.append(
                CachedResource(
                    route=str(prefix),
                    viewset=viewset.__name__,
                    model=model._meta.label,
                    cached=not uncached,
                    ttl=ttl,
                    note=note,
                    reads=reads,
                )
            )
        return sorted(found, key=lambda resource: resource.route)

    def context(self, request: HttpRequest) -> dict[str, Any]:
        from django.conf import settings

        from karni.api.caching import cache_alias, cache_enabled, clearing_method, flush_time

        alias = cache_alias()
        config = (getattr(settings, "CACHES", None) or {}).get(alias, {})
        when = flush_time()
        return {
            **self.site.each_context(request),
            "title": _("API cache"),
            "enabled": cache_enabled(),
            "default_ttl": getattr(settings, "KARNI_API_CACHE_TTL", 300),
            "alias": alias,
            "backend": str(config.get("BACKEND", "")),
            "clearing": clearing_method(),
            "flush": when.describe() if when is not None else "",
            "flush_active": when is not None and cache_enabled(),
            "resources": self.resources(),
        }

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if not self.has_permission(request):
            raise PermissionDenied
        if request.method == "POST":
            return self.post(request)
        return TemplateResponse(request, self.template_name, self.context(request))

    def post(self, request: HttpRequest) -> HttpResponse:
        """``clear=all`` clears every response, ``clear=<app_label.Model>`` one resource's."""
        from django.apps import apps

        from karni.api.caching import clear

        target = str(request.POST.get("clear", "")).strip()
        if target == "all":
            method = clear()
            messages.success(request, _("Cleared every cached response (%s).") % method)
        elif target:
            try:
                model = apps.get_model(target)
            except (LookupError, ValueError):
                messages.error(request, _("No model is called %s.") % target)
            else:
                method = clear(model)
                messages.success(
                    request,
                    _("Cleared the cached responses of %(model)s (%(method)s).")
                    % {"model": model._meta.label, "method": method},
                )
        return HttpResponseRedirect(request.get_full_path())


def install(site: Any, screen: type[ApiCacheScreen] = ApiCacheScreen) -> None:
    """Add the *API cache* screen to ``site``'s URLs and to its index under *Karni*.

    Idempotent: a second call only replaces the screen class. Call it before
    the URLconf reads ``site.urls`` (an ``admin.py`` or an ``AppConfig.ready``).
    """
    first = getattr(site, _INSTALLED, None) is None
    setattr(site, _INSTALLED, screen(site))
    if not first:
        return
    get_urls: Callable[[], list[Any]] = site.get_urls
    get_app_list: Callable[..., list[dict[str, Any]]] = site.get_app_list

    def view(request: HttpRequest) -> HttpResponse:
        current: ApiCacheScreen = getattr(site, _INSTALLED)
        return current(request)

    def urls() -> list[Any]:
        return [path(SCREEN_PATH, site.admin_view(view), name=URL_NAME), *get_urls()]

    def app_list(request: HttpRequest, app_label: str | None = None) -> list[dict[str, Any]]:
        found = get_app_list(request, app_label)
        current: ApiCacheScreen = getattr(site, _INSTALLED)
        if app_label is None and current.has_permission(request):
            found = [*found, _index_entry(site)]
        return found

    site.get_urls = urls
    site.get_app_list = app_list


def _index_entry(site: Any) -> dict[str, Any]:
    """The admin index's *Karni* section with the screen, shaped like an app of models."""
    url = reverse(f"{site.name}:{URL_NAME}")
    return {
        "name": "Karni",
        "app_label": "karni_api_cache",
        "app_url": url,
        "has_module_perms": True,
        "models": [
            {
                "model": None,
                "name": _("API cache"),
                "object_name": "ApiCache",
                "perms": {"add": False, "change": True, "delete": False, "view": True},
                "admin_url": url,
                "add_url": None,
                "view_only": False,
            }
        ],
    }
