"""The row-scope check in one line: a row the client may not see stays hidden on every surface.

::

    assert_row_hidden(client, "/api/events/", their_event, visible=my_event)
    assert_admin_row_hidden(staff_user, their_event, visible=my_event)
    self.assert_row_hidden(client, "/api/events/", their_event)   # in a karni APITestCase

``client`` can list the resource, but ``row`` is outside the rows it may
see: another owner's, outside an ``own`` / ``related:<key>`` grant, outside
a ``Where(...)``. A row-scope denial must look exactly like a row that does
not exist, so every check compares the hidden row with a primary key that
does not exist:

* ``detail`` — GET, PATCH, PUT and DELETE on the row answer what they
  answer for the missing key (404, never a 403 that confirms the row
  exists), with the same error, and the row stays unchanged;
* ``actions`` — every ``@action(detail=True)`` of the viewset (``history``
  included) answers for the row as it does for the missing key;
* ``list`` — the row is not listed, ``count`` matches the rows the pages
  hold, and (the positive control) ``visible``, or at least some row, is;
* ``filters`` — every filter given the row's own value, and ``?id=``, keeps
  it out and the count honest; another resource's relation filter naming
  the row answers as it does for the missing key;
* ``search`` — ``?search=`` with a word of the row (or ``search=``) keeps it
  out; a ``search=`` term the caller says only the row matches finds nothing;
* ``ordering`` — ordering by any field of the response keeps the same rows
  and count (none repeated or dropped), and a model field the response does
  not show cannot reorder the list;
* ``expand`` — no resource relating to the row embeds it, through
  ``?expand=`` or a list of primary keys, when read or in a write's response;
* ``export`` — no export format writes it (also when filtered or searched
  for), and an export of a row pointing at it does not name it.

:func:`assert_admin_row_hidden` is the admin counterpart: the changelist
(and its search) leaves the row out, and the change, history and delete
views, read or posted to, answer exactly as Django's admin answers for a row
that does not exist (a redirect to the index), never with a permission
denial, and leave the row unchanged.

Every failure names the request that leaked and the fix. Each check is a
``check_<name>`` method of :class:`HiddenRowProbe` /
:class:`AdminHiddenRowProbe` and runs on its own with ``checks=["<name>"]``.

Override / escape hatches: ``checks=`` (only these), ``skip=`` (all but
these), ``search=`` (a term only the hidden row matches), ``formats=``
(export formats), and ``probe=`` to run a subclass — override any
``check_<name>`` method, or :meth:`HiddenRowProbe.pointing_rows` to choose
(or create) the rows that relate to the hidden one.
"""

from __future__ import annotations

import io
import json
import re
import uuid
from collections.abc import Iterable, Iterator, Mapping
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from typing import Any, ClassVar, Final

from django.db import models
from django.urls import NoReverseMatch, Resolver404, resolve, reverse

from karni.exceptions import KarniAssertionError
from karni.testing.api import (
    Resource,
    _ids,
    _query_value,
    _search_token,
    _unthrottled,
    client_as,
    resolve_resource,
)

__all__ = [
    "ADMIN_ROW_CHECKS",
    "EXPORT_FORMATS",
    "ROW_CHECKS",
    "AdminHiddenRowProbe",
    "HiddenRowProbe",
    "HiddenRowReport",
    "assert_admin_row_hidden",
    "assert_row_hidden",
]

ROW_CHECKS: Final = (
    "detail",
    "actions",
    "list",
    "filters",
    "search",
    "ordering",
    "expand",
    "export",
)
"""Every check :func:`assert_row_hidden` runs (names for ``checks=`` / ``skip=``)."""

ADMIN_ROW_CHECKS: Final = ("changelist", "views", "writes", "export")
"""Every check :func:`assert_admin_row_hidden` runs (names for ``checks=`` / ``skip=``)."""

EXPORT_FORMATS: Final = ("csv", "xlsx")
"""The export formats probed by default (every format ``/export/`` writes)."""

#: Pages followed per listing before giving up (a page holds the hard maximum page size).
MAX_PAGES: Final = 50

FIX_SCOPE: Final = (
    "the row is inside the client's read scope: narrow the viewset's access.read "
    "(Owned('<owner>'), Granted() with an 'own'/'related:<key>' grant, Where(...)) or its "
    "filter_queryset_for_user, and keep get_queryset()/get_object() overrides on "
    "BaseViewSet's read scope"
)
FIX_LOOKUP: Final = (
    "look the row up through the read scope before any permission check — "
    "BaseViewSet.get_object() does (out of scope is 404; a 403 is only for a row the client "
    "can read but not change) — and never raise PermissionDenied for a row the client "
    "cannot see"
)


@dataclass
class HiddenRowReport:
    """What :func:`assert_row_hidden` / :func:`assert_admin_row_hidden` found."""

    target: str
    passed: list[str] = field(default_factory=list)
    #: The row leaked: a request reached it, embedded it, counted it or confirmed it exists.
    failures: list[str] = field(default_factory=list)
    #: The check proves nothing as set up (the client cannot list, sees no row at all, ...).
    unproven: list[str] = field(default_factory=list)
    #: Probes that could not run here (no export route, nothing relates to the row, ...).
    notes: list[str] = field(default_factory=list)

    def render(self) -> str:
        problems = [*self.failures, *self.unproven]
        lines = [f"{self.target}: {len(problems)} problem(s) ({len(self.passed)} checks passed)"]
        lines += [f"  - {problem}" for problem in problems]
        return "\n".join(lines)

    def raise_for_problems(self) -> None:
        """Raise ``AssertionError`` listing every problem (``E606`` leaks, ``E616`` unproven)."""
        if self.failures:
            raise KarniAssertionError(self.render(), code="E606")
        if self.unproven:
            raise KarniAssertionError(self.render(), code="E616")


@dataclass
class _Listing:
    """Every row a list request reached, page after page."""

    status: int
    ids: list[str] = field(default_factory=list)
    count: int | None = None
    complete: bool = True
    first: list[dict[str, Any]] = field(default_factory=list)


def _selected(
    names: Iterable[str] | None, skip: Iterable[str], known: tuple[str, ...]
) -> list[str]:
    chosen = list(known if names is None else names)
    skipped = set(skip)
    unknown = sorted((set(chosen) | skipped) - set(known))
    if unknown:
        raise KarniAssertionError(
            f"Unknown check(s) {', '.join(unknown)}; the checks are: {', '.join(known)}.",
            code="E603",
        )
    return [name for name in chosen if name not in skipped]


def _body(response: Any) -> bytes:
    if getattr(response, "streaming", False):
        return b"".join(response.streaming_content)
    content: bytes = response.content
    return content


def _mask(text: str, key: Any) -> str:
    """``text`` with ``key`` (a lookup value) replaced wherever it stands as a whole token."""
    return re.sub(rf"(?<![\w-]){re.escape(str(key))}(?![\w-])", "<id>", text)


def _error(response: Any, key: Any) -> str:
    """The error a response states (its ``detail``/``code``), with the lookup ``key`` masked."""
    try:
        data = json.loads(_body(response) or b"null")
    except ValueError:
        return ""
    if isinstance(data, dict):
        text = json.dumps({k: data.get(k) for k in ("detail", "code") if k in data})
    else:
        text = json.dumps(data)
    return _mask(text, key)


def _missing_value(model: type[models.Model], name: str) -> Any:
    """A value of ``model.<name>`` that no row has (a primary key that does not exist)."""
    try:
        model_field = model._meta.get_field(name)
    except Exception:  # noqa: BLE001 - "pk" and unknown names: the primary key
        model_field = model._meta.pk
    manager = model._base_manager
    for attempt in range(1, 100):
        value: Any
        if isinstance(model_field, models.UUIDField):
            value = uuid.uuid4()
        elif isinstance(model_field, models.IntegerField | models.AutoField):
            top = manager.aggregate(top=models.Max(model_field.attname))["top"] or 0
            value = int(top) + 1_000_000 * attempt
        else:
            value = f"karni-missing-{uuid.uuid4().hex[:12]}"
        if not manager.filter(**{model_field.attname: value}).exists():
            return value
    return value


def _client_user(client: Any) -> Any:
    user = getattr(client, "user", None)
    if user is None:
        user = getattr(getattr(client, "handler", None), "_force_user", None)
    return user


def _routed() -> Iterator[Resource]:
    """Every ``BaseViewSet`` on the API router, as a :class:`Resource`."""
    from karni.api.routers import resolve_router
    from karni.api.viewsets import BaseViewSet

    seen: set[str] = set()
    for prefix, viewset, basename in getattr(resolve_router(), "registry", ()):
        if not (isinstance(viewset, type) and issubclass(viewset, BaseViewSet)):
            continue
        if basename in seen:
            continue
        seen.add(basename)
        model = viewset.model or getattr(viewset.queryset, "model", None)
        if model is not None:
            yield Resource(viewset, model, prefix, basename)


@contextmanager
def _all_unthrottled() -> Iterator[None]:
    """Throttling off for every routed viewset while the probe runs (it sends many requests)."""
    with ExitStack() as stack:
        for resource in list(_routed()):
            stack.enter_context(_unthrottled(resource.viewset))
        yield


def _same_model(relation: Any, model: type[models.Model]) -> bool:
    """Whether ``relation`` leads to ``model`` (or a proxy of the same table)."""
    target: Any = getattr(relation, "related_model", None)
    concrete = getattr(getattr(target, "_meta", None), "concrete_model", None)
    return target is model or (concrete is not None and concrete is model._meta.concrete_model)


def _embedded(data: Any, key: str, pk: Any) -> bool:
    """Whether ``data[key]`` (an expanded object or list of them) embeds the row ``pk``."""
    value = data.get(key) if isinstance(data, dict) else None
    rows = value if isinstance(value, list) else [value]
    return any(
        isinstance(row, dict) and str(row.get("id", row.get("pk"))) == str(pk) for row in rows
    )


def _listed_key(data: Any, key: str, pk: Any) -> bool:
    """Whether ``data[key]`` (a list of primary keys) holds ``pk``."""
    value = data.get(key) if isinstance(data, dict) else None
    return isinstance(value, list) and str(pk) in {str(item) for item in value}


class HiddenRowProbe:
    """One hidden row, probed through every API surface (see the module docstring).

    Each ``check_<name>`` method runs one check and records into
    :attr:`report`; :meth:`run` runs several. Subclass to change one check
    (or :meth:`pointing_rows`) and pass the class as ``probe=``.
    """

    checks: ClassVar[tuple[str, ...]] = ROW_CHECKS

    def __init__(
        self,
        client: Any,
        resource: Any,
        row: models.Model,
        *,
        visible: models.Model | None = None,
        search: str | None = None,
        formats: Iterable[str] = EXPORT_FORMATS,
    ) -> None:
        self.client = client if hasattr(client, "get") else client_as(user=client)
        self.user = _client_user(self.client)
        self.row = row
        self.model: type[models.Model] = row._meta.model
        self.visible = visible
        self.search_term = search
        self.formats = tuple(formats)
        self.viewset, self.list_url, self._route = self._resolve(resource)
        self.report = HiddenRowReport(f"assert_row_hidden({self.list_url}, {self._label(row)})")
        self._baseline: _Listing | None = None

    # setup

    def _resolve(self, resource: Any) -> tuple[type[Any], str, str]:
        """``(viewset, list URL, route name stem)`` for a list URL or anything assert_crud takes."""
        if isinstance(resource, str) and resource.startswith("/"):
            path = resource.split("?", 1)[0]
            try:
                match = resolve(path)
            except Resolver404 as exc:
                raise KarniAssertionError(
                    f"assert_row_hidden: {resource!r} resolves to no view; pass the resource's "
                    "list URL (e.g. '/api/events/'), its viewset or its model.",
                    code="E601",
                ) from exc
            viewset = getattr(match.func, "cls", None)
            name = match.view_name or ""
            if viewset is None or not name.endswith("-list"):
                raise KarniAssertionError(
                    f"assert_row_hidden: {resource!r} is not a viewset's list route "
                    f"(it resolves to {name or match.func!r}); pass the list URL, e.g. "
                    "'/api/events/'.",
                    code="E601",
                )
            return viewset, path, name.removesuffix("list")
        found = resolve_resource(resource)
        return found.viewset, found.list_url(), f"{found.basename}-"

    @staticmethod
    def _label(row: models.Model) -> str:
        return f"{row._meta.model.__name__} {row.pk}"

    @property
    def lookup_field(self) -> str:
        return str(getattr(self.viewset, "lookup_field", "pk") or "pk")

    def lookup_value(self, row: models.Model) -> Any:
        name = self.lookup_field
        return row.pk if name in {"pk", row._meta.pk.name} else getattr(row, name)

    def url(self, name: str, value: Any) -> str | None:
        """The route ``<basename>-<name>`` for the lookup ``value`` (``None`` if not routed)."""
        kwarg = str(getattr(self.viewset, "lookup_url_kwarg", None) or self.lookup_field)
        try:
            return reverse(f"{self._route}{name}", kwargs={kwarg: str(value)})
        except NoReverseMatch:
            return None

    def detail_url(self, value: Any) -> str:
        found = self.url("detail", value)
        return found if found is not None else f"{self.list_url}{value}/"

    def missing(self) -> Any:
        """A lookup value no row has: what "does not exist" answers, to compare with."""
        return _missing_value(self.model, self.lookup_field)

    # recording

    def fail(self, check: str, message: str) -> None:
        self.report.failures.append(f"{check}: {message}")

    def unproven(self, check: str, message: str) -> None:
        self.report.unproven.append(f"{check}: {message}")

    def note(self, check: str, message: str) -> None:
        self.report.notes.append(f"{check}: {message}")

    # requests

    def send(self, method: str, url: str, params: Mapping[str, Any] | None = None) -> Any:
        """One request as the client (writes send an empty JSON body)."""
        if params:
            from urllib.parse import urlencode

            url = f"{url}{'&' if '?' in url else '?'}{urlencode(params)}"
        if method == "GET":
            return self.client.get(url)
        call = getattr(self.client, method.lower())
        if hasattr(self.client, "force_authenticate"):  # DRF's APIClient
            return call(url, {}, format="json")
        return call(url, "{}", content_type="application/json")

    @property
    def page(self) -> dict[str, Any]:
        """The query parameter asking for the largest page the API serves."""
        from karni.pagination import hard_max_page_size

        return {"page_size": hard_max_page_size()}

    def collect(self, url: str, params: Mapping[str, Any] | None = None) -> _Listing:
        """Every row a list request reaches, following ``next`` (pages of the hard size cap)."""
        query = {**self.page, **dict(params or {})}
        response = self.send("GET", url, query)
        listing = _Listing(response.status_code)
        if response.status_code != 200:
            return listing
        data = response.json()
        if isinstance(data, dict):
            listing.count = data.get("count") if isinstance(data.get("count"), int) else None
            listing.first = [r for r in data.get("results", []) if isinstance(r, dict)]
        elif isinstance(data, list):
            listing.first = [r for r in data if isinstance(r, dict)]
        listing.ids.extend(_ids(data))
        pages = 1
        following = data.get("next") if isinstance(data, dict) else None
        while following and pages < MAX_PAGES:
            page = self.client.get(following)
            if page.status_code != 200:
                break
            data = page.json()
            listing.ids.extend(_ids(data))
            following = data.get("next") if isinstance(data, dict) else None
            pages += 1
        listing.complete = not following
        return listing

    def baseline(self) -> _Listing:
        """The plain list as the client sees it (fetched once per check)."""
        if self._baseline is None:
            self._baseline = self.collect(self.list_url)
        return self._baseline

    def snapshot(self) -> dict[str, Any] | None:
        """The hidden row as stored (``None`` once it is gone, even soft-deleted rows stay)."""
        found: dict[str, Any] | None = (
            self.model._base_manager.filter(pk=self.row.pk).values().first()
        )
        return found

    def compare(
        self, check: str, method: str, url: str, missing_url: str, missing: Any
    ) -> tuple[int, int]:
        """``method`` on the hidden row must answer as it does on ``missing_url``; the statuses."""
        hidden = self.send(method, url)
        absent = self.send(method, missing_url)
        status = hidden.status_code
        hidden_key = self.lookup_value(self.row)
        if 200 <= status < 300:
            self.fail(check, f"{method} {url} answered {status}, expected 404: {FIX_SCOPE}.")
        elif status != absent.status_code:
            why = " (a 403 confirms the row exists)" if status == 403 else ""
            self.fail(
                check,
                f"{method} {url} answered {status} for the hidden row but "
                f"{absent.status_code} for a row that does not exist{why}, expected 404: "
                f"{FIX_LOOKUP}.",
            )
        elif _error(hidden, hidden_key) != _error(absent, missing):
            self.fail(
                check,
                f"{method} {url} answered {status} with a different error for the hidden row "
                f"({_error(hidden, hidden_key)}) than for a row that does not exist "
                f"({_error(absent, missing)}), which tells the row exists: answer both "
                "with the same error.",
            )
        return status, absent.status_code

    def invariants(self, check: str, label: str, listing: _Listing, *, same_rows: bool) -> bool:
        """A filtered/searched/ordered listing: no hidden row, an honest count, no new rows."""
        before = len(self.report.failures)
        hidden = str(self.row.pk)
        if hidden in listing.ids:
            self.fail(check, f"{label} returns the hidden row: {FIX_SCOPE}.")
        if listing.complete and listing.count is not None and listing.count != len(listing.ids):
            self.fail(
                check,
                f"{label}: count is {listing.count} but the pages hold {len(listing.ids)} "
                "row(s), so the count includes rows the client cannot see: count the same "
                "read-scoped queryset you paginate (self.filter_queryset(self.get_queryset())).",
            )
        base = self.baseline()
        if base.complete and listing.complete:
            extra = sorted(set(listing.ids) - set(base.ids) - {hidden})
            if extra:
                self.fail(
                    check,
                    f"{label} returns row(s) the plain list does not ({', '.join(extra)}): a "
                    "parameter must only narrow the read scope, never widen it.",
                )
            repeated = sorted({pk for pk in listing.ids if listing.ids.count(pk) > 1})
            if same_rows and repeated:
                self.fail(
                    check,
                    f"{label} repeats row(s) {', '.join(repeated)}: the order joins a to-many "
                    "relation, one row per related row (readable or not), so it reveals how "
                    "many there are and pushes other rows off the page. Leave to-many "
                    "relations out of ordering_fields (Karni's derived ordering does).",
                )
            elif same_rows and set(listing.ids) != set(base.ids):
                self.fail(
                    check,
                    f"{label} returns different rows than the plain list: ordering must only "
                    "reorder them.",
                )
        return len(self.report.failures) == before

    # the run

    def run(self, checks: Iterable[str] | None = None) -> HiddenRowReport:
        """Run ``checks`` (default: every one) and return the report (never raises)."""
        with _all_unthrottled():
            for name in self.checks if checks is None else checks:
                before = len(self.report.failures) + len(self.report.unproven)
                self._baseline = None  # a check may add rows (pointing_rows may create them)
                getattr(self, f"check_{name}")()
                if len(self.report.failures) + len(self.report.unproven) == before:
                    self.report.passed.append(name)
        return self.report

    # the checks

    def check_detail(self) -> None:
        """GET/PATCH/PUT/DELETE answer for the hidden row as for a missing one; nothing changes."""
        before = self.snapshot()
        missing = self.missing()
        url = self.detail_url(self.lookup_value(self.row))
        missing_url = self.detail_url(missing)
        absent = 404
        for method in ("GET", "PATCH", "PUT", "DELETE"):
            _status, answered = self.compare("detail", method, url, missing_url, missing)
            absent = answered if method == "GET" else absent
        after = self.snapshot()
        if after is None:
            self.fail("detail", f"DELETE {url} deleted the hidden row: {FIX_LOOKUP}.")
        elif after != before:
            self.fail("detail", f"a write to {url} changed the hidden row: {FIX_LOOKUP}.")
        if absent != 404:
            self.note(
                "detail",
                f"GET on a missing row answers {absent}, not 404: the client cannot retrieve "
                "this resource at all, so the hidden row is out of reach for a role reason",
            )

    def check_actions(self) -> None:
        """Every ``@action(detail=True)`` answers for the hidden row as for a missing one."""
        before = self.snapshot()
        missing = self.missing()
        probed = 0
        for extra in self.viewset.get_extra_actions():
            if not getattr(extra, "detail", False):
                continue
            url = self.url(extra.url_name, self.lookup_value(self.row))
            missing_url = self.url(extra.url_name, missing)
            if url is None or missing_url is None:
                self.note("actions", f"{extra.__name__}: its route needs more than the lookup")
                continue
            for method in sorted(getattr(extra, "mapping", {}) or {"get": extra.__name__}):
                if method.upper() in {"HEAD", "OPTIONS"}:
                    continue
                probed += 1
                self.compare("actions", method.upper(), url, missing_url, missing)
        if not probed:
            self.note("actions", f"{self.viewset.__name__} routes no detail action")
        if self.snapshot() != before:
            self.fail("actions", f"a detail action changed the hidden row: {FIX_LOOKUP}.")

    def check_list(self) -> None:
        """Not listed; the count is honest; ``visible`` (or some row) is (the positive control)."""
        listing = self.baseline()
        if listing.status != 200:
            self.unproven(
                "list",
                f"GET {self.list_url} answered {listing.status}: the client cannot list the "
                "resource, so every row is out of reach for a role reason and this proves no "
                "row scope. Pass a client that can list it (assert_crud covers the denials).",
            )
            return
        self.invariants("list", f"GET {self.list_url}", listing, same_rows=False)
        if self.visible is not None:
            if str(self.visible.pk) not in listing.ids:
                self.unproven(
                    "list",
                    f"positive control: GET {self.list_url} does not list the visible row "
                    f"{self.visible.pk}, so the hidden one could be missing for any reason. "
                    "Pass visible=<a row the client can see>.",
                )
            else:
                url = self.detail_url(self.lookup_value(self.visible))
                status = self.send("GET", url).status_code
                if status != 200:
                    self.unproven("list", f"positive control: GET {url} answered {status}")
        elif not listing.ids:
            self.unproven(
                "list",
                f"positive control: GET {self.list_url} lists no row at all, so every check "
                "passes vacuously. Give the client a row of its own and pass it as visible=.",
            )

    def filter_params(self, viewset: type[Any], model: type[models.Model]) -> dict[str, Any]:
        """``param -> filter`` of ``viewset``'s filterset as the client sees it."""
        from django_filters.rest_framework import DjangoFilterBackend
        from rest_framework.request import Request
        from rest_framework.test import APIRequestFactory

        from karni.api.filters import KarniFilterBackend

        view = viewset()
        view.action = "list"
        view.request = Request(APIRequestFactory().get("/"))
        if self.user is not None:
            view.request.user = self.user
        view.format_kwarg = None
        view.args, view.kwargs = (), {}
        backend = next(
            (
                b()
                for b in getattr(view, "filter_backends", ())
                if isinstance(b, type) and issubclass(b, DjangoFilterBackend)
            ),
            None,
        )
        if backend is None:
            return {}
        filterset = backend.get_filterset_class(view, model._default_manager.all())
        if filterset is None and isinstance(backend, KarniFilterBackend):
            filterset = backend.derive_filterset_class(model)
        return dict(getattr(filterset, "base_filters", {}) or {})

    def row_value(self, path: str) -> Any:
        value: Any = self.row
        for part in path.split("__"):
            value = getattr(value, part, None)
            if value is None or isinstance(value, models.Manager):
                return None
        return value

    def filter_probes(self) -> list[tuple[str, str]]:
        """``(param, value)`` pairs that match the hidden row: its own values, and ``?id=``."""
        probes: list[tuple[str, str]] = []
        for param, declared in self.filter_params(self.viewset, self.model).items():
            if getattr(declared, "method", None) or declared.lookup_expr in {"isnull", "in"}:
                continue
            value = self.row_value(str(declared.field_name))
            if value is not None:
                probes.append((param, _query_value(value)))
        for param in ("id", "pk"):
            if param not in {p for p, _v in probes}:
                probes.append((param, str(self.row.pk)))
        return probes

    def check_filters(self) -> None:
        """Filters on the hidden row's values keep it out; relation filters on it tell nothing."""
        for param, value in self.filter_probes():
            listing = self.collect(self.list_url, {param: value})
            if listing.status == 200:
                label = f"GET {self.list_url}?{param}={value}"
                self.invariants("filters", label, listing, same_rows=False)
        missing = _missing_value(self.model, self.model._meta.pk.name)
        for resource in _routed():
            for param, declared in self.filter_params(resource.viewset, resource.model).items():
                if declared.lookup_expr != "exact":
                    continue
                try:
                    relation = resource.model._meta.get_field(str(declared.field_name))
                except Exception:  # noqa: BLE001 - a traversal or a computed filter
                    continue
                if not (relation.is_relation and _same_model(relation, self.model)):
                    continue
                url = resource.list_url()
                hidden = self.send("GET", url, {param: self.row.pk})
                absent = self.send("GET", url, {param: missing})
                if hidden.status_code != absent.status_code:
                    self.fail(
                        "filters",
                        f"GET {url}?{param}=<the hidden row> answered {hidden.status_code} but "
                        f"{absent.status_code} for a row that does not exist, which tells the "
                        "row exists: give the relation filter the readable rows as its choices "
                        "(Karni's filterset_fields do; a hand-written ModelChoiceFilter needs "
                        "queryset=lambda request: karni.api.access.readable(<qs>, request)).",
                    )

    def check_search(self) -> None:
        """``?search=`` with a word of the hidden row (or ``search=``) does not find it."""
        from rest_framework.settings import api_settings

        fields = tuple(getattr(self.viewset, "search_fields", None) or ())
        if not fields:
            self.note("search", f"{self.viewset.__name__} declares no search_fields")
            return
        term = self.search_term
        if term is None:
            term = next((t for f in fields if (t := _search_token(self.row, str(f)))), "")
        if not term:
            self.note("search", "the hidden row has no searchable word; pass search='<term>'")
            return
        param = str(api_settings.SEARCH_PARAM)
        listing = self.collect(self.list_url, {param: term})
        label = f"GET {self.list_url}?{param}={term}"
        if listing.status != 200:
            self.fail("search", f"{label} answered {listing.status}")
            return
        self.invariants("search", label, listing, same_rows=False)
        if self.search_term is not None and listing.ids:
            self.fail(
                "search",
                f"{label} finds {len(listing.ids)} row(s), but search= names a term only the "
                f"hidden row matches: {FIX_SCOPE}.",
            )

    def check_ordering(self) -> None:
        """Ordering keeps the rows and the count; an unreadable field cannot reorder them."""
        from rest_framework.settings import api_settings

        base = self.baseline()
        if base.status != 200:
            return
        from rest_framework.filters import OrderingFilter

        param = str(api_settings.ORDERING_PARAM)
        for backend in getattr(self.viewset, "filter_backends", ()):
            if isinstance(backend, type) and issubclass(backend, OrderingFilter):
                param = str(getattr(backend, "ordering_param", param))
        shown = [str(key) for key in (base.first[0] if base.first else {})]
        for name in shown:
            for term in (name, f"-{name}"):
                listing = self.collect(self.list_url, {param: term})
                if listing.status == 200:
                    label = f"GET {self.list_url}?{param}={term}"
                    self.invariants("ordering", label, listing, same_rows=True)
        if len(base.ids) < 2:
            self.note(
                "ordering",
                "fewer than two visible rows: a reordering by an unreadable field cannot show",
            )
            return
        for model_field in self.model._meta.concrete_fields:
            if model_field.name in shown:
                continue
            up = self.collect(self.list_url, {param: model_field.name})
            down = self.collect(self.list_url, {param: f"-{model_field.name}"})
            if up.status == 200 and down.status == 200 and up.ids != down.ids:
                self.fail(
                    "ordering",
                    f"GET {self.list_url}?{param}={model_field.name} and "
                    f"?{param}=-{model_field.name} order the rows differently, but "
                    f"{model_field.name} is not in the response: ordering by a field the "
                    "client cannot read reveals its values. Leave ordering_fields unset "
                    "(Karni orders by what the serializer reads back) or drop it from them.",
                )

    def relations_into(self, resource: Resource) -> list[tuple[str | None, Any]]:
        """``(expand key or None, relation)`` of ``resource`` that point at the hidden row's model.

        Every expandable relation (forward or a listed reverse one) whose
        target is the model, plus forward to-many relations (rendered as
        lists of primary keys) that are not expandable.
        """
        from karni.api.expansion import auto_expandable_fields

        declared = resource.viewset.expandable_fields
        mapping = dict(declared) if declared is not None else auto_expandable_fields(resource.model)
        found: list[tuple[str | None, Any]] = []
        seen: set[str] = set()
        for key, name in mapping.items():
            try:
                relation = resource.model._meta.get_field(name)
            except Exception:  # noqa: BLE001 - expandable_fields names no relation
                continue
            if _same_model(relation, self.model):
                found.append((key, relation))
                seen.add(relation.name)
        for relation in resource.model._meta.many_to_many:
            if relation.name not in seen and _same_model(relation, self.model):
                found.append((None, relation))
        return found

    def pointing_rows(self, resource: Resource, relation: Any) -> list[models.Model]:
        """Rows of ``resource`` related to the hidden row through ``relation`` (up to three).

        Override / escape hatch: create a row the client can read when none
        exists (``assert_isolated`` does).
        """
        queryset = resource.model._default_manager.filter(**{relation.name: self.row})
        return list(queryset.distinct()[:3])

    def check_expand(self) -> None:
        """No resource relating to the hidden row embeds it, read or in a write's response."""
        probed = 0
        for resource in _routed():
            for key, relation in self.relations_into(resource):
                many = bool(relation.many_to_many or relation.one_to_many)
                for pointing in self.pointing_rows(resource, relation):
                    url = resource.detail_url(pointing.pk)
                    probed += self._probe_pointing(resource, url, key, relation.name, many)
                if key is not None:
                    listing_url = resource.list_url()
                    response = self.send("GET", listing_url, {"expand": key, **self.page})
                    if response.status_code == 200:
                        data = response.json()
                        rows = data.get("results", data) if isinstance(data, dict) else data
                        if any(_embedded(r, key, self.row.pk) for r in rows or []):
                            self.fail(
                                "expand",
                                f"GET {listing_url}?expand={key} embeds the hidden "
                                f"{self.model.__name__} {self.row.pk}: the expansion must go "
                                f"through {self.model.__name__}'s read scope (do not hand-roll "
                                "the nested serializer or a prefetch that skips it).",
                            )
        if not probed:
            self.note(
                "expand",
                f"no row the client can read relates to the hidden {self.model.__name__}; "
                "create one to exercise ?expand= and lists of primary keys",
            )

    def _probe_pointing(
        self, resource: Resource, url: str, key: str | None, name: str, many: bool
    ) -> int:
        reads = self.send("GET", url)
        if reads.status_code != 200:
            return 0
        fix = (
            f"related rows in a response must be readable: render {name} with Karni's "
            "generated serializer (karni.api.related checks every path), or check custom "
            "serializers/actions with karni.api.related.readable_related"
        )
        what = f"the hidden {self.model.__name__} {self.row.pk}"
        if many and _listed_key(reads.json(), name, self.row.pk):
            self.fail("expand", f"GET {url} lists {what} in {name}: {fix}.")
        if key is not None:
            expanded = self.send("GET", url, {"expand": key})
            if expanded.status_code == 200 and _embedded(expanded.json(), key, self.row.pk):
                self.fail("expand", f"GET {url}?expand={key} embeds {what}: {fix}.")
        written = self.send("PATCH", url)
        if written.status_code == 200 and many and _listed_key(written.json(), name, self.row.pk):
            self.fail("expand", f"PATCH {url} answers with {what} in {name}: {fix}.")
        if key is not None and written.status_code == 200:
            expanded = self.send("PATCH", url, {"expand": key})
            if expanded.status_code == 200 and _embedded(expanded.json(), key, self.row.pk):
                self.fail(
                    "expand", f"PATCH {url}?expand={key} answers with {what} embedded: {fix}."
                )
        return 1

    def check_export(self) -> None:
        """No export format writes the hidden row, nor names it in a related row's column."""
        url = f"{self.list_url}export/"
        base = self.baseline()
        probes: list[dict[str, Any]] = [{}]
        fields = tuple(getattr(self.viewset, "search_fields", None) or ())
        term = self.search_term or next(
            (t for f in fields if (t := _search_token(self.row, str(f)))), ""
        )
        if term:
            probes.append({"search": term})
        probes.extend({param: value} for param, value in self.filter_probes()[:3])
        for fmt, params in ((fmt, params) for fmt in self.formats for params in probes):
            table = self._export(url, fmt, params)
            if table is None:
                break
            headers, rows = table
            label = f"GET {url}?format={fmt}" + "".join(f"&{k}={v}" for k, v in params.items())
            ids = self._column(headers, rows, "id")
            hidden = str(self.row.pk)
            if hidden in ids or (not ids and any(hidden in map(str, row) for row in rows)):
                self.fail("export", f"{label} writes the hidden row: {FIX_SCOPE}.")
            listed = base.complete and base.status == 200
            if not params and listed and len(rows) != len(base.ids):
                self.fail(
                    "export",
                    f"{label} writes {len(rows)} row(s) but the list holds {len(base.ids)}: "
                    "export the list's read-scoped queryset (self.filter_queryset("
                    "self.get_queryset())).",
                )
        self._check_related_exports()

    def _export(
        self, url: str, fmt: str, params: Mapping[str, Any]
    ) -> tuple[list[str], list[list[Any]]] | None:
        from karni.transfer.formats import read_table

        response = self.send("GET", url, {"format": fmt, **params})
        if response.status_code in {404, 405}:
            self.note("export", f"{url} is not routed (no export)")
            return None
        if response.status_code != 200:
            self.note("export", f"GET {url}?format={fmt} answered {response.status_code}")
            return None
        return read_table(io.BytesIO(_body(response)), fmt)

    @staticmethod
    def _column(headers: list[str], rows: list[list[Any]], name: str) -> list[str]:
        if name not in headers:
            return []
        index = headers.index(name)
        return [str(row[index]) for row in rows if index < len(row)]

    def _check_related_exports(self) -> None:
        """An export of a row pointing at the hidden one never writes its natural key."""
        from karni.meta import natural_key

        key = natural_key(self.model)
        named = getattr(self.row, key, None) if key else None
        if named is None or str(named) in {"", str(self.row.pk)}:
            return
        for resource in _routed():
            for _key, relation in self.relations_into(resource):
                if not getattr(relation, "concrete", False):
                    continue
                pointing = self.pointing_rows(resource, relation)
                if not pointing:
                    continue
                url = f"{resource.list_url()}export/"
                response = self.send("GET", url, {"format": "csv"})
                if response.status_code != 200:
                    continue
                from karni.transfer.formats import read_table

                headers, rows = read_table(io.BytesIO(_body(response)), "csv")
                if relation.name not in headers or "id" not in headers:
                    continue
                column, ids = headers.index(relation.name), headers.index("id")
                wanted = {str(row.pk) for row in pointing}
                for row in rows:
                    if str(row[ids]) in wanted and str(named) in str(row[column]).split("|"):
                        self.fail(
                            "export",
                            f"GET {url} names the hidden {self.model.__name__} by its natural "
                            f"key {named!r} in column {relation.name!r}: an export may name "
                            "only related rows the client can read (karni.transfer resolves "
                            "natural keys through karni.api.related's scope).",
                        )
                        break


def assert_row_hidden(
    client: Any,
    resource: Any,
    row: models.Model,
    *,
    visible: models.Model | None = None,
    checks: Iterable[str] | None = None,
    skip: Iterable[str] = (),
    search: str | None = None,
    formats: Iterable[str] = EXPORT_FORMATS,
    probe: type[HiddenRowProbe] | None = None,
) -> HiddenRowReport:
    """Assert ``row`` is hidden from ``client`` on every API surface of ``resource``.

    :param client: an authenticated API client (``client_as(...)``) or a user.
    :param resource: the resource's list URL (``"/api/events/"``), or a viewset
        class, model class, route prefix or ``"app.Model"``.
    :param row: the row the client must not see (outside its row scope).
    :param visible: a row the client does see (the positive control).
    :param checks: run only these (:data:`ROW_CHECKS`); ``skip``: all but these.
    :param search: a term only ``row`` matches (default: a word from its search fields).
    :param formats: export formats to probe (default :data:`EXPORT_FORMATS`).
    :param probe: a :class:`HiddenRowProbe` subclass to run instead (default: that class).
    :raises AssertionError: listing every leak (``E606``) or why nothing is proven (``E616``).
    """
    probe = probe or HiddenRowProbe
    names = _selected(checks, skip, probe.checks)
    runner = probe(client, resource, row, visible=visible, search=search, formats=formats)
    report = runner.run(names)
    report.raise_for_problems()
    return report


class AdminHiddenRowProbe:
    """One hidden row, probed through the admin (see the module docstring).

    Django's admin answers a row that does not exist with a redirect to the
    index; a row outside the user's admin row scope (:mod:`karni.admin.scope`)
    must get exactly that answer.
    """

    checks: ClassVar[tuple[str, ...]] = ADMIN_ROW_CHECKS

    def __init__(
        self,
        client: Any,
        row: models.Model,
        *,
        visible: models.Model | None = None,
        site: Any = None,
        search: str | None = None,
    ) -> None:
        from django.test import Client

        from karni.scoping import admin_site

        if hasattr(client, "get"):
            self.client = client
        else:
            self.client = Client()
            self.client.force_login(client)
        self.row = row
        self.model: type[models.Model] = row._meta.model
        self.visible = visible
        self.search_term = search
        self.site = site if site is not None else admin_site()
        opts = self.model._meta
        self.stem = f"{self.site.name}:{opts.app_label}_{opts.model_name}"
        self.report = HiddenRowReport(
            f"assert_admin_row_hidden({opts.label}, {self.model.__name__} {row.pk})"
        )

    def fail(self, check: str, message: str) -> None:
        self.report.failures.append(f"{check}: {message}")

    def unproven(self, check: str, message: str) -> None:
        self.report.unproven.append(f"{check}: {message}")

    def note(self, check: str, message: str) -> None:
        self.report.notes.append(f"{check}: {message}")

    def url(self, view: str, pk: Any = None) -> str | None:
        try:
            return reverse(f"{self.stem}_{view}", args=[] if pk is None else [pk])
        except NoReverseMatch:
            return None

    def snapshot(self) -> dict[str, Any] | None:
        found: dict[str, Any] | None = (
            self.model._base_manager.filter(pk=self.row.pk).values().first()
        )
        return found

    def missing(self) -> Any:
        return _missing_value(self.model, self.model._meta.pk.name)

    def run(self, checks: Iterable[str] | None = None) -> HiddenRowReport:
        if self.model not in self.site._registry:
            self.unproven(
                "admin",
                f"{self.model._meta.label} is not registered on the admin site "
                f"{self.site.name!r} (KARNI_ADMIN_SITE), so there is nothing to probe",
            )
            return self.report
        for name in self.checks if checks is None else checks:
            before = len(self.report.failures) + len(self.report.unproven)
            getattr(self, f"check_{name}")()
            if len(self.report.failures) + len(self.report.unproven) == before:
                self.report.passed.append(name)
        return self.report

    def _shown(self, response: Any) -> set[str] | None:
        changelist = response.context_data.get("cl") if response.context_data else None
        if changelist is None:
            return None
        return {str(pk) for pk in changelist.queryset.values_list("pk", flat=True)}

    def check_changelist(self) -> None:
        """The changelist, its search and a primary-key filter leave the hidden row out."""
        url = self.url("changelist")
        response = self.client.get(url) if url else None
        if response is None or response.status_code != 200:
            status = "not routed" if response is None else f"answered {response.status_code}"
            self.unproven(
                "changelist",
                f"the changelist {url or ''} {status}: the user cannot open it, so this proves "
                "no row scope. Log in a staff user with the model's view permission.",
            )
            return
        shown = self._shown(response)
        if shown is None:
            self.note("changelist", "the changelist rendered without a ChangeList context")
            return
        hidden = str(self.row.pk)
        fix = (
            "the admin must list only the rows the user's grants reach — keep "
            "KarniAdminMixin.get_queryset (karni.admin.scope) in the chain, or drop "
            "scope_exempt"
        )
        if hidden in shown:
            self.fail("changelist", f"GET {url} lists the hidden row: {fix}.")
        if self.visible is not None and str(self.visible.pk) not in shown:
            self.unproven(
                "changelist",
                f"positive control: GET {url} does not list the visible row {self.visible.pk}",
            )
        elif self.visible is None and not shown:
            self.unproven(
                "changelist",
                f"positive control: GET {url} lists no row at all; pass visible=<a row the "
                "user sees>",
            )
        model_admin = self.site._registry[self.model]
        term = self.search_term
        if term is None:
            fields = tuple(model_admin.get_search_fields(response.wsgi_request))
            term = next((t for f in fields if (t := _search_token(self.row, str(f)))), "")
        probes = [{"q": term}] if term else []
        probes.append({self.model._meta.pk.name: hidden})
        for params in probes:
            searched = self.client.get(url, params)
            found = self._shown(searched) if searched.status_code == 200 else None
            if found is not None and hidden in found:
                query = "&".join(f"{k}={v}" for k, v in params.items())
                self.fail("changelist", f"GET {url}?{query} finds the hidden row: {fix}.")

    def _compare(self, check: str, method: str, view: str, data: Mapping[str, Any]) -> None:
        missing = self.missing()
        url, missing_url = self.url(view, self.row.pk), self.url(view, missing)
        if url is None or missing_url is None:
            self.note(check, f"the admin routes no {view} view")
            return
        send = self.client.get if method == "GET" else self.client.post
        hidden = send(url, dict(data)) if method == "POST" else send(url)
        absent = send(missing_url, dict(data)) if method == "POST" else send(missing_url)
        status = hidden.status_code
        where = tuple(
            _mask(str(response.get("Location") or ""), key) or None
            for response, key in ((hidden, self.row.pk), (absent, missing))
        )
        if status == 200 and absent.status_code != 200:
            self.fail(
                check,
                f"{method} {url} answered 200 for the hidden row: the admin opened a row "
                "outside the user's scope — keep KarniAdminMixin.get_queryset in the chain "
                "so get_object() finds nothing.",
            )
        elif status != absent.status_code or where[0] != where[1]:
            why = " (a 403 confirms the row exists)" if status == 403 else ""
            self.fail(
                check,
                f"{method} {url} answered {status} ({where[0] or 'no redirect'}) for the "
                f"hidden row but {absent.status_code} ({where[1] or 'no redirect'}) for a row "
                f"that does not exist{why}: Django's admin answers a row it cannot find with "
                "a redirect to the index, so let get_queryset() decide (karni.admin.scope) and "
                "keep has_*_permission(request, obj) for rows that are found.",
            )

    def check_views(self) -> None:
        """The change, history and delete views answer for the hidden row as for a missing one."""
        for view in ("change", "history", "delete"):
            self._compare("views", "GET", view, {})

    def check_writes(self) -> None:
        """Posting to the change and delete views answers as for a missing row; nothing changes."""
        before = self.snapshot()
        self._compare("writes", "POST", "change", {"_save": "1"})
        self._compare("writes", "POST", "delete", {"post": "yes"})
        if self.snapshot() != before:
            self.fail("writes", "a POST through the admin changed or deleted the hidden row.")

    def check_export(self) -> None:
        """The export actions, given the hidden row's id, do not write it."""
        url = self.url("changelist")
        if url is None:
            return
        model_admin = self.site._registry[self.model]
        if not getattr(model_admin, "karni_transfer", False):
            self.note("export", "the admin has no export actions (karni_transfer = False)")
            return
        for action in ("export_csv", "export_xlsx"):
            response = self.client.post(
                url, {"action": action, "_selected_action": [str(self.row.pk)]}
            )
            if response.status_code != 200:
                continue
            body = _body(response)
            if action == "export_xlsx":
                from karni.transfer.formats import read_table

                _headers, rows = read_table(io.BytesIO(body), "xlsx")
                text = json.dumps(rows, default=str)
            else:
                text = body.decode("utf-8", "replace")
            if str(self.row.pk) in text:
                self.fail(
                    "export",
                    f"POST {url} action={action} with the hidden row selected exports it: "
                    "actions must run on the changelist's scoped queryset.",
                )


def assert_admin_row_hidden(
    client: Any,
    row: models.Model,
    *,
    visible: models.Model | None = None,
    checks: Iterable[str] | None = None,
    skip: Iterable[str] = (),
    site: Any = None,
    search: str | None = None,
    probe: type[AdminHiddenRowProbe] | None = None,
) -> HiddenRowReport:
    """Assert ``row`` behaves as "does not exist" in the admin for ``client``'s staff user.

    :param client: a ``django.test.Client`` logged in as a staff user, or the user.
    :param row: the row outside the user's admin row scope.
    :param visible: a row the user does see in the changelist (the positive control).
    :param checks: run only these (:data:`ADMIN_ROW_CHECKS`); ``skip``: all but these.
    :param site: the admin site (default: ``KARNI_ADMIN_SITE``).
    :param search: a changelist search term only ``row`` matches.
    :param probe: an :class:`AdminHiddenRowProbe` subclass to run instead (default: that class).
    :raises AssertionError: listing every leak (``E606``) or why nothing is proven (``E616``).
    """
    probe = probe or AdminHiddenRowProbe
    names = _selected(checks, skip, probe.checks)
    report = probe(client, row, visible=visible, site=site, search=search).run(names)
    report.raise_for_problems()
    return report
