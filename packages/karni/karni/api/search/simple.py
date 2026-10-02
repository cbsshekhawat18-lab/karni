"""Database-agnostic fallback search provider."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from django.db.models import Q, QuerySet

from karni.api.search import SearchProvider

__all__ = ["SimpleSearchProvider"]


class SimpleSearchProvider(SearchProvider):
    """``icontains`` search: OR of one case-insensitive match per field.

    The whole query string is matched as a single substring against each field
    (``field__icontains=query``) and the per-field conditions are OR-ed
    together. This works on every database backend (including SQLite, which is
    why ``tests/settings.py`` selects it) but does no ranking, so
    ``rank_order`` is accepted and ignored.

    Divergence from DRF's ``SearchFilter`` (documented, intentional): the query
    is **not** split into terms, and the ``^`` / ``=`` / ``@`` / ``$``
    field-prefix syntax is not supported — ``fields`` are plain ORM lookup
    paths (``"title"``, ``"venue__name"``). Note that a path crossing a
    to-many relation can duplicate rows; add ``.distinct()`` in a subclass if
    you search such paths.

    Override / escape hatch: subclass and change :attr:`lookup` (for example to
    ``"istartswith"``) or override :meth:`search` entirely, then point the
    ``KARNI_SEARCH_PROVIDER`` setting at your subclass.
    """

    lookup: str = "icontains"
    """ORM lookup applied to every field; override in a subclass to change it."""

    def search(
        self,
        *,
        queryset: QuerySet[Any],
        query: str,
        fields: Sequence[str],
        view: Any | None = None,
        rank_order: bool = True,
    ) -> QuerySet[Any]:
        """Return rows where any of ``fields`` contains ``query``."""
        if not query or not fields:
            return queryset
        condition = Q()
        for field in fields:
            condition |= Q(**{f"{field}__{self.lookup}": query})
        return queryset.filter(condition)
