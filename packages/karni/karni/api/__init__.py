"""Karni's declarative API layer.

The one import most projects need::

    from karni.api import Access, BaseViewSet, HasRole, Public

    class EventViewSet(BaseViewSet):
        model = Event
        access = Access(read=Public(), write=HasRole("staff"))
        search_fields = ["title"]

That declaration alone yields CRUD, filtering, pagination, ordering, search,
access control, ``?expand=``, query optimisation and OpenAPI schema. The
supporting machinery lives in the submodules — :mod:`karni.api.access` (the
``access`` vocabulary), :mod:`karni.api.serializers` (generation),
:mod:`karni.api.related` (related rows in a response are readable ones),
:mod:`karni.api.optimizer` (select/prefetch from the serializer),
:mod:`karni.api.caching`, :mod:`karni.api.expansion`, :mod:`karni.api.filters`,
:mod:`karni.api.routers` / :mod:`karni.api.urls` (autodiscovery) and
:mod:`karni.api.schema` — each documenting its own escape hatches.

The performance declarations are re-exported here too: ``Budget``
(:mod:`karni.performance`), ``Unpaginated`` (:mod:`karni.pagination`),
``Cache`` / ``Uncached`` (:mod:`karni.api.caching`).

The re-export is lazy (PEP 562) on purpose: DRF resolves Karni's default
``DEFAULT_FILTER_BACKENDS`` (``karni.api.filters``) while
``rest_framework.viewsets`` is still initialising, so this package's import
must never pull in :mod:`karni.api.viewsets` (or :mod:`karni.api.access`)
as a side effect.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from karni.api.access import (
        Access,
        Authenticated,
        Can,
        Granted,
        HasRole,
        Owned,
        Public,
        Unscoped,
        Where,
    )
    from karni.api.caching import Cache, Uncached
    from karni.api.viewsets import BaseViewSet
    from karni.pagination import Unpaginated
    from karni.performance import Budget

__all__ = [
    "Access",
    "Authenticated",
    "BaseViewSet",
    "Budget",
    "Cache",
    "Can",
    "Granted",
    "HasRole",
    "Owned",
    "Public",
    "Uncached",
    "Unpaginated",
    "Unscoped",
    "Where",
]

_LAZY = {
    "Access": "karni.api.access",
    "Authenticated": "karni.api.access",
    "BaseViewSet": "karni.api.viewsets",
    "Budget": "karni.performance",
    "Cache": "karni.api.caching",
    "Can": "karni.api.access",
    "Granted": "karni.api.access",
    "HasRole": "karni.api.access",
    "Owned": "karni.api.access",
    "Public": "karni.api.access",
    "Uncached": "karni.api.caching",
    "Unpaginated": "karni.pagination",
    "Unscoped": "karni.api.access",
    "Where": "karni.api.access",
}


def __getattr__(name: str) -> Any:
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(import_module(module), name)


def __dir__() -> list[str]:
    return sorted([*__all__, *globals()])
