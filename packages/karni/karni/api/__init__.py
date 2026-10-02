"""Karni's declarative API layer.

The one import most projects need::

    from karni.api import BaseViewSet

    class EventViewSet(BaseViewSet):
        model = Event
        search_fields = ["title"]

That declaration alone yields CRUD, filtering, pagination, ordering, search,
permissions, ``?expand=`` and OpenAPI schema. The supporting machinery lives
in the submodules — :mod:`karni.api.serializers` (generation),
:mod:`karni.api.expansion`, :mod:`karni.api.filters`,
:mod:`karni.api.routers` / :mod:`karni.api.urls` (autodiscovery) and
:mod:`karni.api.schema` — each documenting its own escape hatches.

The re-export is lazy (PEP 562) on purpose: DRF resolves Karni's default
``DEFAULT_FILTER_BACKENDS`` (``karni.api.filters``) while
``rest_framework.viewsets`` is still initialising, so this package's import
must never pull in :mod:`karni.api.viewsets` as a side effect.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from karni.api.viewsets import BaseViewSet

__all__ = ["BaseViewSet"]


def __getattr__(name: str) -> Any:
    if name == "BaseViewSet":
        from karni.api.viewsets import BaseViewSet

        return BaseViewSet
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted([*__all__, *globals()])
