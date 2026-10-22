"""Karni's pagination: on for every list, capped, and off only by a declaration.

ADR 0001 Decision 3 (Q3.4–Q3.6). Every ``BaseViewSet`` list is paginated by a
:class:`KarniPagination` subclass:

* :class:`KarniPageNumberPagination` (the default, ``?page=`` /
  ``?page_size=``) and :class:`KarniCursorPagination` (``?cursor=``, for very
  large tables where ``COUNT(*)`` hurts).
* **Hard cap.** ``?page_size=`` — and the default ``PAGE_SIZE`` — are capped
  at ``KARNI_MAX_PAGE_SIZE`` (default 100). A paginator subclass may set a
  lower ``max_page_size``, never a higher one.
* **Floor.** ``KARNI_MAX_PAGE_SIZE`` cannot be configured below
  ``KARNI_MAX_PAGE_SIZE_FLOOR`` (default 25, the page size ``@karni/ui``'s
  ``ResourceTable`` requests; never below 1). A cap of ``0``/``None`` would
  switch DRF's cap off, and a cap below what the UI requests silently hides
  rows from its page math — so boot validation refuses both.
* **Opt-out.** ``pagination = Unpaginated(max_rows=N, reason="...")`` on a
  viewset: the response is a plain list, still sliced at ``max_rows``, with
  ``X-Karni-Truncated: true`` when rows were cut. ``pagination_class = None``
  without it is a class-definition error, and boot refuses
  ``REST_FRAMEWORK["PAGE_SIZE"] = None`` or a non-Karni default class.

Override / escape hatches: subclass a Karni paginator (lower
``max_page_size``, another ``page_size_query_param``) and point
``pagination_class`` or ``REST_FRAMEWORK["DEFAULT_PAGINATION_CLASS"]`` at it;
raise ``KARNI_MAX_PAGE_SIZE``; lower ``KARNI_MAX_PAGE_SIZE_FLOOR`` (explicitly)
for a project that serves no ``ResourceTable``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Final

from django.conf import settings
from rest_framework.pagination import BasePagination, CursorPagination, PageNumberPagination
from rest_framework.request import Request
from rest_framework.response import Response

from karni.exceptions import KarniImproperlyConfigured

__all__ = [
    "DEFAULT_MAX_PAGE_SIZE",
    "DEFAULT_MAX_PAGE_SIZE_FLOOR",
    "DEFAULT_PAGE_SIZE",
    "KarniCursorPagination",
    "KarniPageNumberPagination",
    "KarniPagination",
    "Unpaginated",
    "UnpaginatedPagination",
    "hard_max_page_size",
]

DEFAULT_MAX_PAGE_SIZE: Final = 100
"""Fallback for ``KARNI_MAX_PAGE_SIZE`` (ADR 0001 Q3.4)."""

DEFAULT_MAX_PAGE_SIZE_FLOOR: Final = 25
"""Fallback for ``KARNI_MAX_PAGE_SIZE_FLOOR``: ``ResourceTable``'s page size."""

DEFAULT_PAGE_SIZE: Final = 50
"""Page size used when ``REST_FRAMEWORK["PAGE_SIZE"]`` is missing."""

TRUNCATED_HEADER: Final = "X-Karni-Truncated"


def hard_max_page_size() -> int:
    """``KARNI_MAX_PAGE_SIZE``, never below 1 (validation enforces the real floor)."""
    value = getattr(settings, "KARNI_MAX_PAGE_SIZE", DEFAULT_MAX_PAGE_SIZE)
    return max(int(value or 1), 1)


class KarniPagination(BasePagination):
    """Marker base: only paginators deriving from it are accepted by ``BaseViewSet``.

    Subclasses cap page sizes through :meth:`get_max_page_size`.
    """

    #: A subclass may set a lower cap; ``None`` = ``KARNI_MAX_PAGE_SIZE``.
    max_page_size: Any = None

    def get_max_page_size(self) -> int:
        """The effective cap: ``max_page_size`` if lower, else ``KARNI_MAX_PAGE_SIZE``."""
        hard = hard_max_page_size()
        own = type(self).max_page_size
        if isinstance(own, int) and not isinstance(own, bool) and 0 < own < hard:
            return own
        return hard

    def get_default_page_size(self) -> int:
        """``REST_FRAMEWORK["PAGE_SIZE"]`` (or :data:`DEFAULT_PAGE_SIZE`), capped."""
        from rest_framework.settings import api_settings

        configured = getattr(self, "page_size", None) or api_settings.PAGE_SIZE
        return min(int(configured or DEFAULT_PAGE_SIZE), self.get_max_page_size())


def _requested_size(request: Request, param: str | None) -> int | None:
    if not param:
        return None
    raw = request.query_params.get(param)
    try:
        size = int(raw) if raw is not None else 0
    except ValueError:
        return None
    return size if size > 0 else None


class KarniPageNumberPagination(KarniPagination, PageNumberPagination):
    """Page-number pagination: ``?page=`` and a capped ``?page_size=``.

    Envelope: ``{count, next, previous, results}``. The default size is
    ``REST_FRAMEWORK["PAGE_SIZE"]`` (env ``KARNI_PAGE_SIZE``, 50); a request
    may ask for any size up to :meth:`get_max_page_size`.

    Override / escape hatch: subclass it (e.g. ``max_page_size = 20`` for a
    heavy endpoint) and set ``pagination_class`` on the viewset or
    ``REST_FRAMEWORK["DEFAULT_PAGINATION_CLASS"]``.
    """

    page_size_query_param = "page_size"

    def get_page_size(self, request: Request) -> int:
        requested = _requested_size(request, self.page_size_query_param)
        if requested is None:
            return self.get_default_page_size()
        return min(requested, self.get_max_page_size())


class KarniCursorPagination(KarniPagination, CursorPagination):
    """Cursor pagination for very large tables (no ``COUNT(*)``).

    Ordering comes from the view's ``ordering`` (``BaseViewSet`` derives one:
    ``Meta.ordering``, ``-created_at`` or ``-pk``). Envelope:
    ``{next, previous, results}``; ``?page_size=`` is capped like the
    page-number paginator.
    """

    page_size_query_param = "page_size"

    def get_page_size(self, request: Request) -> int:
        requested = _requested_size(request, self.page_size_query_param)
        if requested is None:
            return self.get_default_page_size()
        return min(requested, self.get_max_page_size())


class UnpaginatedPagination(KarniPagination):
    """The paginator behind :class:`Unpaginated`: a plain list, sliced at ``max_rows``.

    Fetches ``max_rows + 1`` rows to know whether it cut anything; a cut
    response carries ``X-Karni-Truncated: true``.
    """

    max_rows: ClassVar[int] = 0
    reason: ClassVar[str] = ""

    def paginate_queryset(self, queryset: Any, request: Request, view: Any = None) -> list[Any]:
        rows = list(queryset[: self.max_rows + 1])
        self.truncated = len(rows) > self.max_rows
        return rows[: self.max_rows]

    def get_paginated_response(self, data: Any) -> Response:
        headers = {TRUNCATED_HEADER: "true"} if getattr(self, "truncated", False) else None
        return Response(data, headers=headers)

    def get_paginated_response_schema(self, schema: dict[str, Any]) -> dict[str, Any]:
        return schema

    def get_schema_operation_parameters(self, view: Any) -> list[dict[str, Any]]:
        return []

    def get_results(self, data: Any) -> Any:
        return data


@dataclass(frozen=True, kw_only=True)
class Unpaginated:
    """``pagination = Unpaginated(max_rows=N, reason="...")``: a viewset that returns lists.

    The only way to switch pagination off on a ``BaseViewSet``. Lists come
    back as a plain JSON array of at most ``max_rows`` rows (more are cut,
    and the response says so with ``X-Karni-Truncated: true``). Both
    arguments are mandatory; ``karni context`` lists every unpaginated
    viewset with its reason.
    """

    max_rows: int
    reason: str

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_rows, bool)
            or not isinstance(self.max_rows, int)
            or self.max_rows <= 0
        ):
            raise KarniImproperlyConfigured(
                f"Unpaginated(max_rows={self.max_rows!r}) needs a positive row limit, because "
                "unbounded responses are not allowed.",
                code="E113",
            )
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise KarniImproperlyConfigured(
                'Unpaginated(max_rows=..., reason="...") needs a non-empty reason saying why '
                "this list is not paginated (e.g. reason='CSV export').",
                code="E113",
            )

    def paginator_class(self) -> type[UnpaginatedPagination]:
        """A paginator class bound to this declaration."""
        attrs = {"max_rows": self.max_rows, "reason": self.reason, "__module__": __name__}
        return type("Unpaginated", (UnpaginatedPagination,), attrs)


def check_pagination_class(owner: str, value: object) -> None:
    """Raise unless ``value`` is a :class:`KarniPagination` subclass (for messages: ``owner``)."""
    if value is None:
        raise KarniImproperlyConfigured(
            f"{owner}.pagination_class = None switches pagination off. Lists must stay "
            "bounded: declare pagination = Unpaginated(max_rows=N, reason='...') instead "
            "(ADR 0001 Q3.5).",
            code="E111",
        )
    if not (isinstance(value, type) and issubclass(value, KarniPagination)):
        raise KarniImproperlyConfigured(
            f"{owner}.pagination_class = {value!r} is not a karni.pagination.KarniPagination "
            "subclass. Subclass KarniPageNumberPagination or KarniCursorPagination (they "
            "enforce KARNI_MAX_PAGE_SIZE).",
            code="E112",
        )
