"""The list screen's table basics: page size, a count that stays cheap, page links, chips.

Every Karni admin list shows ``Showing 1 to 25 of 312 notes`` with page
links at the bottom, a page-size choice kept in the URL (``?per_page=50``),
and the active filters and search as chips above the table. The pieces here
are plain classes the admin wires in (:class:`KarniPaginator` as the admin's
``paginator``, :class:`KarniChangeListMixin` in front of its ``ChangeList``):

* **Page size.** ``KARNI_ADMIN_PER_PAGE`` (25) is the default, ``AdminMeta.per_page``
  or ``list_per_page`` on an admin class sets one model's, and ``?per_page=``
  picks one of ``karni_per_page_choices`` (25, 50, 100 and the model's own).
  Any other value is ignored, so a URL cannot ask for a million rows.
* **A count that stays cheap.** On PostgreSQL, once a table holds more than
  ``KARNI_ADMIN_COUNT_ESTIMATE_ABOVE`` rows (100000, ``0`` turns it off), the
  planner's estimate stands in for ``COUNT(*)`` and the list says "about".
  A list the estimate puts under the threshold is still counted exactly.
* **Chips.** Each active filter is a chip with a remove link, and the search
  term has one too, with ``Clear all`` (:meth:`KarniChangeListMixin.karni_chips`).

Override / escape hatch: set ``paginator`` on an admin to use another class,
override ``get_changelist`` for another change list, or change a setting.
"""

from __future__ import annotations

import json
from typing import Any

from django.conf import settings
from django.contrib.admin.views.main import PAGE_VAR, SEARCH_VAR
from django.core.exceptions import EmptyResultSet
from django.core.paginator import Paginator
from django.db import DatabaseError, connections, transaction
from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils.formats import number_format
from django.utils.functional import cached_property
from django.utils.text import capfirst
from django.utils.translation import gettext as _

__all__ = [
    "COUNT_ESTIMATE_ABOVE",
    "PER_PAGE",
    "PER_PAGE_CHOICES",
    "PER_PAGE_VAR",
    "KarniChangeListMixin",
    "KarniPaginator",
    "count_rows",
    "count_estimate_above",
    "per_page_default",
]

PER_PAGE = 25
"""Fallback for the ``KARNI_ADMIN_PER_PAGE`` setting."""

PER_PAGE_CHOICES: tuple[int, ...] = (25, 50, 100)
"""The page sizes the list offers, besides the model's own."""

COUNT_ESTIMATE_ABOVE = 100_000
"""Fallback for ``KARNI_ADMIN_COUNT_ESTIMATE_ABOVE``."""

PER_PAGE_VAR = "per_page"
"""The query parameter that carries the page size."""


def per_page_default() -> int:
    """Rows per page when nothing else says (``KARNI_ADMIN_PER_PAGE``)."""
    return max(int(getattr(settings, "KARNI_ADMIN_PER_PAGE", PER_PAGE)), 1)


def count_estimate_above() -> int:
    """The table size above which PostgreSQL counts are estimates (``0``: never)."""
    return max(int(getattr(settings, "KARNI_ADMIN_COUNT_ESTIMATE_ABOVE", COUNT_ESTIMATE_ABOVE)), 0)


def _plan_rows(queryset: QuerySet[Any], threshold: int) -> int | None:
    """The planner's row estimate when it is above ``threshold``, else ``None`` (count exactly).

    Any database error (an unusual table name, a view, a failed plan) also gives
    ``None``: the exact count is always the fallback, never an error page.
    """
    connection = connections[queryset.db]
    if connection.vendor != "postgresql":
        return None
    table = queryset.model._meta.db_table
    named = table if ('"' in table or "." in table) else connection.ops.quote_name(table)
    try:
        sql, params = queryset.order_by().query.sql_with_params()
    except EmptyResultSet:
        return None
    try:
        with transaction.atomic(using=queryset.db), connection.cursor() as cursor:
            cursor.execute(
                "SELECT reltuples::bigint FROM pg_class WHERE oid = to_regclass(%s)", [named]
            )
            row = cursor.fetchone()
            if row is None or row[0] is None or row[0] <= threshold:
                return None  # a small or never analysed table: counting is cheap or the only truth
            cursor.execute(f"EXPLAIN (FORMAT JSON) {sql}", params)
            plan = cursor.fetchone()
    except DatabaseError:
        return None
    if plan is None:
        return None
    document = json.loads(plan[0]) if isinstance(plan[0], str | bytes) else plan[0]
    guess = int(document[0]["Plan"]["Plan Rows"])
    return guess if guess > threshold else None


def count_rows(queryset: QuerySet[Any]) -> tuple[int, bool]:
    """``(rows, estimated)``: an exact ``COUNT`` unless the table is large (module docstring)."""
    threshold = count_estimate_above()
    if threshold:
        guess = _plan_rows(queryset, threshold)
        if guess is not None:
            return guess, True
    return queryset.count(), False


class KarniPaginator(Paginator):  # type: ignore[type-arg]
    """Django's paginator with :func:`count_rows`; ``estimated`` says the count is a guess."""

    estimated: bool = False

    @cached_property
    def count(self) -> int:  # type: ignore[override]
        if isinstance(self.object_list, QuerySet):
            total, self.estimated = count_rows(self.object_list)
            return total
        return int(super().count)


class _RootCount:
    """Stands in for ``root_queryset`` while results load, so ``N total`` is cheap too."""

    def __init__(self, source: Any) -> None:
        self.source = source

    def count(self) -> int:
        if isinstance(self.source, QuerySet):
            return count_rows(self.source)[0]
        return int(self.source.count())


class KarniChangeListMixin:
    """Mixed in front of the admin's ``ChangeList``: page size, page links, summary, chips.

    ``list_per_page`` for one request comes from ``request._karni_per_page``, which
    the admin sets (:meth:`KarniAdminMixin.karni_page_size`).
    """

    # what ChangeList provides
    params: dict[str, Any]
    query: str
    page_num: int
    list_per_page: int
    result_count: int
    result_list: Any
    paginator: Any
    show_all: bool
    can_show_all: bool
    multi_page: bool
    opts: Any
    model_admin: Any
    filter_specs: list[Any]
    has_active_filters: bool | None
    root_queryset: Any
    get_query_string: Any

    def __init__(self, request: HttpRequest, *args: Any, **kwargs: Any) -> None:
        # list_per_page is the ninth argument (after request): see ChangeList.__init__
        args_list = list(args)
        if len(args_list) >= 8 and hasattr(request, "_karni_per_page"):
            args_list[7] = request._karni_per_page
        super().__init__(request, *args_list, **kwargs)  # type: ignore[misc,call-arg]

    def get_filters_params(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        found: dict[str, Any] = super().get_filters_params(params)  # type: ignore[misc]
        found.pop(PER_PAGE_VAR, None)
        return found

    def get_results(self, request: HttpRequest) -> None:
        original = self.root_queryset
        self.root_queryset = _RootCount(original)
        try:
            super().get_results(request)  # type: ignore[misc]
        finally:
            self.root_queryset = original

    # -- what the template shows ---------------------------------------------

    def _name(self, count: int) -> str:
        return str(self.opts.verbose_name if count == 1 else self.opts.verbose_name_plural)

    def karni_summary(self) -> dict[str, Any] | None:
        """``Showing 1 to 25 of 312 notes`` (``about`` when counted by estimate), or ``None``."""
        total = int(self.result_count)
        if total == 0:
            return None
        shown = len(self.result_list)
        first = (
            1
            if (self.show_all and self.can_show_all)
            else (self.page_num - 1) * self.list_per_page + 1
        )
        last = min(first + shown - 1, total) if shown else first
        estimated = bool(getattr(self.paginator, "estimated", False))
        figure = number_format(total, use_l10n=True, force_grouping=True)
        values = {
            "first": number_format(first, use_l10n=True, force_grouping=True),
            "last": number_format(max(last, first), use_l10n=True, force_grouping=True),
            "total": figure,
            "name": self._name(total),
        }
        if estimated:
            text = _("Showing %(first)s to %(last)s of about %(total)s %(name)s") % values
        else:
            text = _("Showing %(first)s to %(last)s of %(total)s %(name)s") % values
        return {"text": text, "estimated": estimated, "total": total}

    def karni_pages(self) -> list[dict[str, Any]]:
        """Page links with gaps: ``1 2 3 ... 13``. Empty for a single page."""
        pages = int(self.paginator.num_pages)
        if pages <= 1 or (self.show_all and self.can_show_all):
            return []
        current = min(max(self.page_num, 1), pages)
        wanted = {1, pages, *range(current - 1, current + 2)}
        if current <= 2:
            wanted |= {2, 3}
        if current >= pages - 1:
            wanted |= {pages - 2, pages - 1}
        links: list[dict[str, Any]] = []
        previous = 0
        for number in sorted(n for n in wanted if 1 <= n <= pages):
            if number - previous > 1:
                links.append({"gap": True})
            links.append(
                {
                    "gap": False,
                    "number": number,
                    "current": number == current,
                    "url": self.get_query_string({PAGE_VAR: number}),
                }
            )
            previous = number
        return links

    def karni_neighbours(self) -> dict[str, str | None]:
        """The previous and next page URLs, ``None`` at either end."""
        pages = int(self.paginator.num_pages)
        current = min(max(self.page_num, 1), pages)
        if pages <= 1 or (self.show_all and self.can_show_all):
            return {"previous": None, "next": None}
        return {
            "previous": self.get_query_string({PAGE_VAR: current - 1}) if current > 1 else None,
            "next": self.get_query_string({PAGE_VAR: current + 1}) if current < pages else None,
        }

    def karni_sizes(self) -> list[dict[str, Any]]:
        """The page-size choices as links that keep the filters, search and sort."""
        choices = self.model_admin.karni_page_sizes()
        return [
            {
                "size": size,
                "current": size == self.list_per_page,
                "url": self.get_query_string({PER_PAGE_VAR: size}),
            }
            for size in choices
        ]

    def karni_chips(self) -> list[dict[str, str]]:
        """One chip per active filter value, each with the URL that removes it."""
        chips: list[dict[str, str]] = []
        for spec in getattr(self, "filter_specs", ()):
            used = getattr(spec, "used_parameters", None)
            if not used:
                continue
            remove = self.get_query_string(remove=list(spec.expected_parameters()))
            shown: list[str] = []
            try:
                for choice in spec.choices(self):
                    if choice.get("selected") and str(choice.get("display")) != str(_("All")):
                        shown.append(str(choice["display"]))
            except Exception:  # noqa: BLE001 - a custom filter that cannot list choices keeps its title
                shown = []
            title = capfirst(str(spec.title))
            for value in shown or [""]:
                chips.append({"label": f"{title}: {value}" if value else title, "remove": remove})
        return chips

    def karni_clear_url(self) -> str:
        """The list with no search and no filter (sort and page size stay)."""
        names = [*self.get_filters_params(), SEARCH_VAR]
        return str(self.get_query_string(remove=names))

    def karni_search_clear_url(self) -> str:
        """The list without the search term (filters stay)."""
        return str(self.get_query_string(remove=[SEARCH_VAR]))

    def karni_narrowed(self) -> bool:
        """Whether a search or a filter is on."""
        return bool(self.query or self.karni_chips() or self.get_filters_params())
