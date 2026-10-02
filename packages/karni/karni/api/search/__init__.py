"""Pluggable search providers for Karni's API layer.

:class:`karni.api.filters.KarniSearchFilter` never touches the ORM itself; it
hands the queryset to the provider returned by :func:`get_search_provider`.
Swapping the whole search implementation (PostgreSQL full-text, Elasticsearch,
Meilisearch, ...) is therefore a one-setting change — no viewset or project
code is affected.

Override / escape hatch: point the ``KARNI_SEARCH_PROVIDER`` setting at any
dotted path whose target is a zero-argument callable returning a
:class:`SearchProvider` (normally a ``SearchProvider`` subclass). The default
is :class:`karni.api.search.postgres.PostgresSearchProvider`;
``tests/settings.py`` uses :class:`karni.api.search.simple.SimpleSearchProvider`
because it works on SQLite.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.core.signals import setting_changed
from django.dispatch import receiver
from django.utils.module_loading import import_string

if TYPE_CHECKING:
    from django.db.models import QuerySet

__all__ = ["DEFAULT_SEARCH_PROVIDER", "SearchProvider", "get_search_provider"]

DEFAULT_SEARCH_PROVIDER = "karni.api.search.postgres.PostgresSearchProvider"
"""Dotted path used when the ``KARNI_SEARCH_PROVIDER`` setting is absent."""


class SearchProvider(ABC):
    """Interface every Karni search backend implements.

    Providers must be stateless (one cached instance serves every request) and
    must return a queryset **of the same model** they were given, so the rest
    of the filter/pagination pipeline keeps working unchanged.

    Override / escape hatch: subclass, implement :meth:`search`, and point the
    ``KARNI_SEARCH_PROVIDER`` setting at your subclass.
    """

    @abstractmethod
    def search(
        self,
        *,
        queryset: QuerySet[Any],
        query: str,
        fields: Sequence[str],
        view: Any | None = None,
        rank_order: bool = True,
    ) -> QuerySet[Any]:
        """Return ``queryset`` narrowed down to rows matching ``query``.

        :param queryset: the (already filtered/ordered) queryset to search.
        :param query: the raw ``?search=`` term, stripped, never empty.
        :param fields: ORM field paths to search, from ``view.search_fields``.
        :param view: the calling view, for providers that need extra context.
        :param rank_order: ``True`` when the request carries no explicit
            ``?ordering=`` parameter. Ranking providers must only call
            ``order_by`` when this is ``True``; when it is ``False`` they may
            annotate but must leave the incoming ordering untouched so an
            explicit ``?ordering=`` always wins.
        """


_provider: SearchProvider | None = None


def get_search_provider() -> SearchProvider:
    """Return the configured :class:`SearchProvider` instance (cached).

    Resolves the ``KARNI_SEARCH_PROVIDER`` setting (default
    :data:`DEFAULT_SEARCH_PROVIDER`) with ``import_string`` and instantiates it
    once; subsequent calls return the same instance. The cache is reset when
    ``KARNI_SEARCH_PROVIDER`` changes (Django's ``setting_changed`` signal), so
    ``override_settings(KARNI_SEARCH_PROVIDER=...)`` works in tests.

    Override / escape hatch: set ``KARNI_SEARCH_PROVIDER`` in your project's
    ``settings.py``; no code change is needed anywhere else.
    """
    global _provider
    if _provider is None:
        path: str = getattr(settings, "KARNI_SEARCH_PROVIDER", DEFAULT_SEARCH_PROVIDER)
        _provider = import_string(path)()
    return _provider


@receiver(setting_changed, dispatch_uid="karni.api.search.reset_provider_cache")
def _reset_provider_cache(sender: object, *, setting: str = "", **kwargs: Any) -> None:
    """Drop the cached provider when ``KARNI_SEARCH_PROVIDER`` changes.

    Connected at module import; it reacts only to the one relevant setting so
    unrelated ``override_settings`` blocks never pay the re-import cost.
    """
    if setting == "KARNI_SEARCH_PROVIDER":
        global _provider
        _provider = None
