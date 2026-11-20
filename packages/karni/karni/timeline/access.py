"""Experimental. Who may read a timeline entry: whoever may read every record it is about.

An entry's title was written about its person and its subjects (the order,
the ticket, the deal), so it shows only to a caller who may read each of
them. Each record is checked through the queryset its model's own list
endpoint uses for this request (the routed ``BaseViewSet``'s request gate,
then its ``get_queryset()``: model scopes, row scope, the ``access.read``
filter), the way cross-model search does: one query per model on the page.

A model that no routed ``BaseViewSet`` serves (no API of its own, or a part
that was removed) is readable by superusers only.

Override / escape hatch: ``KARNI_TIMELINE_VISIBILITY`` names a subclass of
:class:`Visibility`; override :meth:`Visibility.readable` for one model's
rule, or :meth:`Visibility.unrouted` for models without an endpoint.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from rest_framework.exceptions import NotAuthenticated, PermissionDenied
from rest_framework.request import Request

from karni.imports import import_setting

__all__ = ["DEFAULT", "Visibility", "get_visibility"]

#: The class ``KARNI_TIMELINE_VISIBILITY`` names by default.
DEFAULT = "karni.timeline.access.Visibility"


class Visibility:
    """Experimental. The records one request may read, asked one model at a time."""

    def __init__(self, request: Request, router: Any | None = None) -> None:
        from karni.api.routers import resolve_router

        self.request = request
        self.router = router if router is not None else resolve_router()
        self._routes: dict[type[models.Model], tuple[str, type[Any]]] | None = None

    def routes(self) -> dict[type[models.Model], tuple[str, type[Any]]]:
        """Each routed model's resource prefix and viewset (the first registered one)."""
        if self._routes is None:
            from karni.api.viewsets import BaseViewSet

            found: dict[type[models.Model], tuple[str, type[Any]]] = {}
            for prefix, viewset, _basename in getattr(self.router, "registry", ()):
                if not (isinstance(viewset, type) and issubclass(viewset, BaseViewSet)):
                    continue
                model = getattr(viewset, "model", None) or getattr(
                    getattr(viewset, "queryset", None), "model", None
                )
                if model is not None and model not in found:
                    found[model] = (str(prefix), viewset)
            self._routes = found
        return self._routes

    def resource(self, model: type[models.Model]) -> str | None:
        """The router prefix that serves ``model`` (a client links to it), or None."""
        route = self.routes().get(model)
        return route[0] if route is not None else None

    def bound_view(self, prefix: str, viewset: type[Any]) -> Any:
        """An instance of ``viewset`` bound to this request, as its ``list`` action."""
        view = viewset()
        view.request = self.request
        view.args = ()
        view.kwargs = {}
        view.format_kwarg = None
        view.action = "list"
        view.detail = False
        view.basename = prefix
        return view

    def queryset(self, model: type[models.Model]) -> models.QuerySet[Any] | None:
        """The rows of ``model`` this request may list, or None when it may list none."""
        route = self.routes().get(model)
        if route is None:
            return None
        view = self.bound_view(*route)
        try:
            view.check_permissions(self.request)
        except (NotAuthenticated, PermissionDenied):
            return None
        queryset: models.QuerySet[Any] = view.get_queryset()
        return queryset.prefetch_related(None)

    def unrouted(self, model: type[models.Model] | None) -> bool:
        """Whether records of a model no routed viewset serves are readable: superusers only."""
        return bool(getattr(getattr(self.request, "user", None), "is_superuser", False))

    def readable(self, model: type[models.Model] | None, ids: Collection[str]) -> set[str]:
        """The ids among ``ids`` (keys as text) of records of ``model`` this request may read.

        One query for a routed model. ``model`` is None for a model that is
        no longer installed.
        """
        if not ids:
            return set()
        if model is None or model not in self.routes():
            return set(ids) if self.unrouted(model) else set()
        queryset = self.queryset(model)
        if queryset is None:
            return set()
        keys: dict[Any, str] = {}
        for raw in ids:
            try:
                keys[model._meta.pk.to_python(raw)] = raw  # type: ignore[union-attr]
            except (ValidationError, TypeError, ValueError):
                continue
        if not keys:
            return set()
        found = queryset.filter(pk__in=list(keys)).values_list("pk", flat=True)
        return {str(pk) for pk in found}


def get_visibility(request: Request, router: Any | None = None) -> Visibility:
    """The ``KARNI_TIMELINE_VISIBILITY`` class, bound to ``request``."""
    cls = import_setting(
        "KARNI_TIMELINE_VISIBILITY", getattr(settings, "KARNI_TIMELINE_VISIBILITY", DEFAULT)
    )
    instance: Visibility = cls(request, router)
    return instance
