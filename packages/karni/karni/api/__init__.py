"""Karni's declarative API layer.

The one import most projects need::

    from karni.api import Access, Authenticated, BaseViewSet, Public

    class EventViewSet(BaseViewSet):
        model = Event
        access = Access(read=Public(), write=Authenticated())
        search_fields = ["title"]

That declaration alone yields CRUD, filtering, pagination, ordering, search,
access control, ``?expand=`` and OpenAPI schema. The supporting machinery
lives in the submodules — :mod:`karni.api.access` (the ``access``
vocabulary), :mod:`karni.api.serializers` (generation),
:mod:`karni.api.expansion`, :mod:`karni.api.filters`,
:mod:`karni.api.routers` / :mod:`karni.api.urls` (autodiscovery) and
:mod:`karni.api.schema` — each documenting its own escape hatches.

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
        HasRole,
        Owned,
        Public,
        Unscoped,
        Where,
    )
    from karni.api.viewsets import BaseViewSet

__all__ = [
    "Access",
    "Authenticated",
    "BaseViewSet",
    "Can",
    "HasRole",
    "Owned",
    "Public",
    "Unscoped",
    "Where",
]

_LAZY = {name: "karni.api.access" for name in __all__ if name != "BaseViewSet"}
_LAZY["BaseViewSet"] = "karni.api.viewsets"


def __getattr__(name: str) -> Any:
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(import_module(module), name)


def __dir__() -> list[str]:
    return sorted([*__all__, *globals()])
