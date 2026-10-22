"""Why an endpoint runs the queries it runs: ``karni queries`` (``manage.py karni_queries``).

:func:`run` requests one endpoint in-process — the test client,
force-authenticated as a user, inside a transaction that is rolled back —
and records every SQL statement with the stack that issued it
(:class:`StackRecorder`, built on :class:`karni.performance.QueryRecorder`).
The repeated statements are then grouped by **cause**: the serializer field
being rendered, the relation it read, why the optimiser did not fetch it and
the hint that fixes it. The "why" comes from the optimiser's own plan:
:func:`karni.api.optimizer.blind_spots` lists what the walker could not see
(a ``SerializerMethodField``, a model property, a ``to_representation``),
and :func:`karni.api.optimizer.planned_lookups` what it did fetch::

    GET /api/events/ as organizer@example.com → 200 · EventViewSet.list
    28 queries — 12 from TicketTier.booking_set (an aggregate per row),
    6 from Event.venue not prefetched

Development only: it runs your view against your database (writes are rolled
back, ``on_commit`` callbacks never fire), with the response cache and the
query budget off so every statement is counted.

Override / escape hatch: each step is a public function — :func:`resolve_user`,
:func:`resolve_endpoint`, :func:`run`, :func:`analyse` and
:meth:`Report.render` — for project tooling that wants a different report.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import re
import sys
import time
import traceback
from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import Any, Final
from urllib.parse import urlsplit

from django.apps import apps
from django.conf import settings
from django.db import connections, transaction
from django.db.models import Model
from django.test.utils import override_settings
from django.urls import NoReverseMatch, Resolver404, resolve, reverse

from karni.exceptions import KarniLookupError, KarniValueError
from karni.performance import (
    QueryRecorder,
    field_label,
    is_project_frame,
    rendering_field,
    short_path,
    short_sql,
)

__all__ = [
    "Cause",
    "Report",
    "StackRecorder",
    "Target",
    "TracedQuery",
    "analyse",
    "resolve_endpoint",
    "resolve_user",
    "run",
]

logger = logging.getLogger("karni.queries")

#: Statements that manage the transaction, never an N+1.
_CONTROL: Final = ("SAVEPOINT", "RELEASE SAVEPOINT", "ROLLBACK", "BEGIN", "COMMIT", "SET ")
_AGGREGATE = re.compile(
    r"^\s*SELECT\s+(?:DISTINCT\s+)?(?P<func>COUNT|SUM|AVG|MIN|MAX)\((?:DISTINCT\s+)?"
    r"(?:\*|\"?(?P<table>\w+)\"?\.\"?(?P<column>\w+)\"?)\)",
    re.IGNORECASE,
)
_EXISTS = re.compile(
    r"^\s*SELECT\s+(?:\(?1\)?|1 AS \"a\")\b.*\bLIMIT 1\s*$", re.IGNORECASE | re.DOTALL
)
_EQUALS = re.compile(r"\"(?P<table>\w+)\"\.\"(?P<column>\w+)\" = %s")
_FROM = re.compile(r"\bFROM\s+\"?(?P<table>\w+)\"?", re.IGNORECASE)
_WHERE = re.compile(
    r"\bWHERE\b(?P<where>.*?)(?:\bORDER BY\b|\bLIMIT\b|\bGROUP BY\b|$)", re.I | re.S
)
_OPTIMIZER = "karni/api/optimizer.py"


# recording


@dataclass(frozen=True)
class FieldStep:
    """A serializer field that was rendering when a statement ran."""

    field: Any
    label: str
    #: The model of the rows the field's serializer renders (``None`` when unknown).
    model: type[Model] | None
    #: The row being rendered, when the frame shows it (tells two FKs to one model apart).
    instance: Any = None
    #: True when the field is a nested serializer rendering its own (related) row: the
    #: statement ran one level below the field's parent.
    inside: bool = False


@dataclass(frozen=True)
class TracedQuery:
    """One statement with the stack that issued it."""

    sql: str
    params: Any
    duration: float
    #: Fields being rendered, outermost first
    #: (``EventSerializer.tiers`` → ``TicketTierSerializer.remaining``).
    fields: tuple[FieldStep, ...]
    #: The innermost project frame inside the innermost field (``events/models.py:56``).
    frame: str
    #: The innermost Karni frame, when no project frame issued it.
    karni_frame: str

    @property
    def control(self) -> bool:
        return self.sql.lstrip().upper().startswith(_CONTROL)


def _meta_model(serializer: Any) -> type[Model] | None:
    model = getattr(getattr(serializer, "Meta", None), "model", None)
    return model if isinstance(model, type) and issubclass(model, Model) else None


def _step(field: Any, frame: FrameType, row: tuple[Any, Any] | None) -> FieldStep:
    """The :class:`FieldStep` for ``field`` rendering in ``frame``.

    ``row`` is ``(child serializer, row)`` when a list child's
    ``to_representation`` was seen inside this frame: the statement then ran
    for one row of the list, a level below the field.
    """
    from rest_framework.serializers import BaseSerializer, ListSerializer

    label = field_label(field)
    if isinstance(field, ListSerializer):
        if row is not None and row[0] is field.child:
            child_row = row[1]
            model = type(child_row) if child_row is not None else _meta_model(field.child)
            return FieldStep(field, label, model, child_row, inside=True)
        return FieldStep(field, label, _meta_model(field.parent), None)
    instance = _instance(frame)
    if isinstance(field, BaseSerializer) and frame.f_code.co_name == "to_representation":
        model = _meta_model(field) or (type(instance) if instance is not None else None)
        return FieldStep(field, label, model, instance, inside=True)
    model = _meta_model(field.parent) or (type(instance) if instance is not None else None)
    return FieldStep(field, label, model, instance)


def _list_row(frame: FrameType) -> tuple[Any, Any] | None:
    """``(serializer, row)`` when ``frame`` renders one row of a ``many=True`` serializer."""
    from rest_framework.serializers import BaseSerializer, ListSerializer

    serializer = frame.f_locals.get("self")
    if frame.f_code.co_name != "to_representation" or not isinstance(serializer, BaseSerializer):
        return None
    if not isinstance(getattr(serializer, "parent", None), ListSerializer):
        return None
    return serializer, _instance(frame)


def _instance(frame: FrameType) -> Model | None:
    """The row a field frame renders: ``get_attribute(instance)`` / a method field's value."""
    for name in ("instance", "value", "obj"):
        found = frame.f_locals.get(name)
        if isinstance(found, Model):
            return found
    return None


def _location(frame: FrameType) -> str:
    return f"{short_path(frame.f_code.co_filename)}:{frame.f_lineno} in {frame.f_code.co_name}"


_KARNI_DIR = str(Path(__file__).resolve().parents[1])


def _karni_location(frame: FrameType) -> str:
    relative = Path(frame.f_code.co_filename).relative_to(_KARNI_DIR).as_posix()
    return f"karni/{relative}:{frame.f_lineno} in {frame.f_code.co_name}"


def _capture(frame: FrameType | None) -> tuple[tuple[FieldStep, ...], str, str]:
    """``(fields outermost first, innermost project frame, innermost Karni frame)``.

    The frames are the ones inside the innermost field (or anywhere, when no
    field was rendering): the code that actually issued the statement.
    """
    steps: list[FieldStep] = []
    seen: set[int] = set()
    project = karni = ""
    row: tuple[Any, Any] | None = None
    while frame is not None:
        rendering = rendering_field(frame)
        filename = frame.f_code.co_filename
        if filename == __file__:
            break  # run() made the request: frames past it (manage.py) are not the cause
        if rendering is None and row is None:
            row = _list_row(frame)
        if rendering is not None:
            if id(rendering) not in seen:
                seen.add(id(rendering))
                steps.append(_step(rendering, frame, row))
            row = None
        elif not steps and not project and is_project_frame(frame):
            project = _location(frame)
        elif not steps and not karni and filename.startswith(_KARNI_DIR):
            karni = _karni_location(frame)
        frame = frame.f_back
    steps.reverse()
    return tuple(steps), project, karni


class StackRecorder(QueryRecorder):
    """A :class:`~karni.performance.QueryRecorder` that also keeps each statement's stack."""

    def __init__(self) -> None:
        super().__init__()
        self.traced: list[TracedQuery] = []

    def __call__(
        self,
        execute: Callable[..., Any],
        sql: str,
        params: Any,
        many: bool,
        context: Mapping[str, Any],
    ) -> Any:
        fields, frame, karni = _capture(sys._getframe(1))
        try:
            return super().__call__(execute, sql, params, many, context)
        finally:
            duration = self.queries[-1].duration if self.queries else 0.0
            self.traced.append(TracedQuery(sql, params, duration, fields, frame, karni))


@contextmanager
def recording() -> Iterator[StackRecorder]:
    """Record every statement on every connection, with its stack."""
    recorder = StackRecorder()
    with ExitStack() as stack:
        for alias in connections:
            stack.enter_context(connections[alias].execute_wrapper(recorder))
        yield recorder


# resolving the request


def resolve_user(value: str | None) -> Any | None:
    """The user named by ``value`` (pk, email or username); ``None`` for anonymous.

    :raises KarniLookupError: ``E941`` when no user (or more than one) matches.
    """
    if value is None or value.strip().lower() in ("", "anonymous", "anon", "-"):
        return None
    from django.contrib.auth import get_user_model
    from django.core.exceptions import ValidationError

    user_model = get_user_model()
    manager = user_model._default_manager
    tried: list[str] = []
    lookups: list[dict[str, Any]] = []
    try:
        lookups.append({"pk": user_model._meta.pk.to_python(value)})
        tried.append("pk")
    except (ValidationError, ValueError, TypeError):
        pass
    for name in dict.fromkeys((user_model.USERNAME_FIELD, "email", "username")):
        try:
            user_model._meta.get_field(name)
        except Exception:  # noqa: BLE001 - FieldDoesNotExist: the model has no such field
            continue
        lookups.append({f"{name}__iexact": value})
        tried.append(name)
    for lookup in lookups:
        try:
            found = list(manager.filter(**lookup)[:2])
        except (ValidationError, ValueError, TypeError):
            continue
        if len(found) == 1:
            return found[0]
    examples = ", ".join(
        str(getattr(user, user_model.USERNAME_FIELD, user.pk)) for user in manager.all()[:5]
    )
    names = " or ".join(dict.fromkeys((user_model.USERNAME_FIELD, "email", "primary key")))
    raise KarniLookupError(
        f"--as {value!r} matches no single user (tried {', '.join(tried)}). Name a user by "
        f"{names}"
        + (f", e.g. {examples}" if examples else " (the user table is empty: karni seed)")
        + ", or --as anonymous.",
        code="E941",
    )


@dataclass(frozen=True)
class Target:
    """The request to make: its path (with query string) and the view that answers it."""

    path: str
    view: Any = None
    action: str = ""
    kwargs: Mapping[str, Any] = dataclasses.field(default_factory=dict)

    @property
    def label(self) -> str:
        name = getattr(self.view, "__name__", "") if self.view is not None else ""
        return f"{name}.{self.action}" if name and self.action else name


_VIEWSET_FORM = re.compile(r"^(?P<name>[A-Z]\w*)(?:\.(?P<action>\w+))?(?P<query>\?.*)?$")


def _router() -> Any:
    from karni.api.routers import resolve_router

    return resolve_router()


def _registry() -> list[tuple[str, Any, str]]:
    router = _router()
    return list(getattr(router, "registry", []) or [])


def _reverse(basename: str, suffix: str, kwargs: Mapping[str, Any] | None = None) -> str:
    try:
        return reverse(f"{basename}-{suffix}", kwargs=kwargs)
    except NoReverseMatch:
        from karni.management.commands.karni_routes import collect_routes

        for row in collect_routes():
            if (row["name"] or "").split(":")[-1] == f"{basename}-{suffix}":
                path = str(row["path"])
                for key, value in (kwargs or {}).items():
                    path = re.sub(rf"<(?:\w+:)?{key}>", str(value), path)
                return path
    raise KarniLookupError(
        f"No URL is named {basename}-{suffix}: the router's URLs are not included in the "
        "root URLconf. `karni routes` lists what is.",
        code="E940",
    )


def _first_readable(viewset: Any, user: Any) -> Any:
    from django.contrib.auth.models import AnonymousUser
    from rest_framework.request import Request
    from rest_framework.test import APIRequestFactory

    view = viewset()
    view.action = "retrieve"
    view.request = Request(APIRequestFactory().get("/"))
    view.request.user = user or AnonymousUser()
    view.format_kwarg = None
    view.args, view.kwargs = (), {}
    queryset, _filtered = view.read_scope(view.get_model()._default_manager.all())
    return queryset.order_by("pk").values_list("pk", flat=True).first()


def _from_viewset(name: str, action: str, query: str, user: Any) -> str:
    entry = next(((p, v, b) for p, v, b in _registry() if v.__name__ == name), None)
    if entry is None:
        routed = ", ".join(sorted({v.__name__ for _p, v, _b in _registry()})) or "none"
        raise KarniLookupError(
            f"No routed viewset is named {name}. Routed viewsets: {routed}.", code="E940"
        )
    _prefix, viewset, basename = entry
    extra = {a.__name__: a for a in viewset.get_extra_actions()}
    detail = action in ("retrieve", "update", "partial_update", "destroy") or bool(
        action in extra and extra[action].detail
    )
    if action not in ("list", "create", "retrieve", "update", "partial_update", "destroy"):
        if action not in extra:
            raise KarniLookupError(
                f"{name} has no action {action!r}; its actions: list, retrieve"
                + "".join(f", {a}" for a in sorted(extra))
                + ".",
                code="E940",
            )
    if not detail:
        base = _reverse(basename, "list")
    else:
        pk = _first_readable(viewset, user)
        if pk is None:
            raise KarniLookupError(
                f"{name}.{action} needs a row and this user can read none: pass one, e.g. "
                f"{_prefix}/<id>.",
                code="E940",
            )
        lookup = viewset.lookup_url_kwarg or viewset.lookup_field
        base = _reverse(basename, "detail", {lookup: pk})
    if action in extra:
        base = f"{base}{extra[action].url_path}/"
    return base + query


def _from_resource(resource: str, query: str) -> str | None:
    stripped = resource.strip("/")
    for prefix, _viewset, basename in sorted(_registry(), key=lambda r: -len(r[0])):
        if stripped == prefix:
            return _reverse(basename, "list") + query
        if stripped.startswith(prefix + "/"):
            return _reverse(basename, "list") + stripped[len(prefix) + 1 :] + "/" + query
    return None


def resolve_endpoint(endpoint: str, method: str = "GET", user: Any = None) -> Target:
    """The :class:`Target` for ``/api/events/?x=1``, ``events``, ``events/<id>`` or
    ``EventViewSet[.action]``.

    :raises KarniLookupError: ``E940`` when nothing answers there.
    """
    endpoint = endpoint.strip()
    if endpoint.startswith(("http://", "https://")):
        parts = urlsplit(endpoint)
        endpoint = parts.path + (f"?{parts.query}" if parts.query else "")
    form = _VIEWSET_FORM.match(endpoint)
    if endpoint.startswith("/"):
        path = endpoint
    elif form and form["name"].endswith(("ViewSet", "View")):
        default = "list" if method.upper() == "GET" else "create"
        path = _from_viewset(form["name"], form["action"] or default, form["query"] or "", user)
    else:
        resource, _, query = endpoint.partition("?")
        found = _from_resource(resource, f"?{query}" if query else "")
        if found is None:
            prefixes = ", ".join(sorted(p for p, _v, _b in _registry())) or "none"
            raise KarniLookupError(
                f"{endpoint!r} is not a path, a routed resource or a viewset. Give a path "
                f"(/api/events/), a resource ({prefixes}), resource/<id>, or ViewSetName.action.",
                code="E940",
            )
        path = found
    try:
        match = resolve(urlsplit(path).path)
    except Resolver404:
        raise KarniLookupError(
            f"No URL matches {urlsplit(path).path}; `karni routes` lists every route.",
            code="E940",
        ) from None
    view = getattr(match.func, "cls", None) or getattr(match.func, "view_class", None)
    actions: Mapping[str, str] = getattr(match.func, "actions", None) or {}
    action = actions.get(method.lower(), "")
    if actions and not action:
        allowed = ", ".join(m.upper() for m in actions)
        raise KarniValueError(
            f"{getattr(view, '__name__', 'The view')} does not answer {method.upper()} at "
            f"{urlsplit(path).path}; it answers {allowed}.",
            code="E942",
        )
    return Target(path, view, action, dict(match.kwargs))


# analysing


@dataclass
class Cause:
    """Repeated statements with one cause: a field reading a relation, once per row."""

    count: int
    summary: str
    field: str = ""
    chain: tuple[str, ...] = ()
    relation: str = ""
    kind: str = ""
    why: str = ""
    fix: str = ""
    where: str = ""
    statements: list[tuple[int, str]] = dataclasses.field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "summary": self.summary,
            "field": self.field,
            "chain": list(self.chain),
            "relation": self.relation,
            "kind": self.kind,
            "why": self.why,
            "fix": self.fix,
            "where": self.where,
            "statements": [
                {"count": count, "sql": short_sql(sql, 400)} for count, sql in self.statements
            ],
        }


@dataclass
class Report:
    """What :func:`run` found: totals, causes of repeated statements, the rest."""

    method: str
    path: str
    user: str
    status: int
    view: str
    budget: int | None
    queries: list[TracedQuery]
    causes: list[Cause]
    notes: list[str] = dataclasses.field(default_factory=list)
    plans: list[tuple[str, str]] = dataclasses.field(default_factory=list)

    @property
    def counted(self) -> list[TracedQuery]:
        return [query for query in self.queries if not query.control]

    @property
    def total(self) -> int:
        return len(self.counted)

    @property
    def duration_ms(self) -> float:
        return sum(query.duration for query in self.counted) * 1000

    @property
    def repeated(self) -> int:
        return sum(cause.count for cause in self.causes)

    def once(self) -> list[tuple[int, str, str]]:
        """Statements that are not part of a cause: ``(count, sql, origin)``."""
        explained = {sql for cause in self.causes for _count, sql in cause.statements}
        counts: Counter[str] = Counter(query.sql for query in self.counted)
        origins = {query.sql: _origin(query) for query in self.counted}
        return [(count, sql, origins[sql]) for sql, count in counts.items() if sql not in explained]

    def headline(self) -> str:
        parts = [f"{cause.count} from {cause.summary}" for cause in self.causes[:4]]
        tail = f" — {', '.join(parts)}" if parts else " — no statement repeats"
        return f"{self.total} queries{tail}"

    def as_dict(self, *, every: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "request": {"method": self.method, "path": self.path, "as": self.user},
            "status": self.status,
            "view": self.view,
            "budget": self.budget,
            "queries": self.total,
            "time_ms": round(self.duration_ms, 2),
            "repeated": self.repeated,
            "headline": self.headline(),
            "causes": [cause.as_dict() for cause in self.causes],
            "once": [
                {"count": count, "sql": short_sql(sql, 400), "origin": origin}
                for count, sql, origin in self.once()
            ],
            "notes": self.notes,
        }
        if self.plans:
            data["explain"] = [{"sql": sql, "plan": plan} for sql, plan in self.plans]
        if every:
            data["statements"] = [
                {"sql": query.sql, "ms": round(query.duration * 1000, 3), "origin": _origin(query)}
                for query in self.counted
            ]
        return data

    def render(self, *, every: bool = False) -> str:
        """The text ``karni queries`` prints."""
        who = self.user or "anonymous"
        view = f" · {self.view}" if self.view else ""
        lines = [f"{self.method} {self.path} as {who} → {self.status}{view}", self.headline()]
        totals = f"{self.duration_ms:.1f} ms in SQL"
        if self.budget is not None:
            over = self.total - self.budget
            totals += f"; budget {self.budget}" + (f", {over} over" if over > 0 else ", within")
        lines.append(totals)
        for cause in self.causes:
            lines.append("")
            lines.append(f"{cause.count}× {cause.summary}")
            if cause.chain:
                lines.append(f"  field  {' → '.join(cause.chain)}")
            if cause.where:
                lines.append(f"  where  {cause.where}")
            lines.append(f"  why    {cause.why}")
            lines.append(f"  fix    {cause.fix}")
            for count, sql in cause.statements[:3]:
                lines.append(f"  sql    {count}× {brief_sql(sql)}")
        once = self.once()
        if once:
            lines.append("")
            lines.append(f"Ran once each ({sum(count for count, _s, _o in once)}):")
            for count, sql, origin in once[: None if every else 8]:
                suffix = f"  ← {origin}" if origin else ""
                prefix = f"{count}× " if count > 1 else ""
                lines.append(f"  {prefix}{brief_sql(sql, 110)}{suffix}")
            if not every and len(once) > 8:
                lines.append(f"  … {len(once) - 8} more (--all lists every statement)")
        for sql, plan in self.plans:
            lines.append("")
            lines.append(f"EXPLAIN {short_sql(sql, 110)}")
            lines.extend(f"  {line}" for line in plan.splitlines())
        for note in self.notes:
            lines.append("")
            lines.append(f"note: {note}")
        return "\n".join(lines)


def brief_sql(sql: str, width: int = 140) -> str:
    """:func:`karni.performance.short_sql`, keeping an aggregate's select list (``SUM(…)``)."""
    match = _AGGREGATE.search(sql)
    if match is None:
        return short_sql(sql, width)
    text = " ".join(sql.split())
    head = text[: text.upper().find(" FROM ")]
    rest = short_sql(sql, width).removeprefix("SELECT … ")
    full = f"{head} {rest}"
    return full if len(full) <= width else full[: width - 1] + "…"


def _origin(query: TracedQuery) -> str:
    if query.fields:
        inner = query.fields[-1].label
        return f"{inner} ({query.frame})" if query.frame else inner
    return query.frame or query.karni_frame


def _tables() -> dict[str, type[Model]]:
    return {model._meta.db_table: model for model in apps.get_models(include_auto_created=True)}


@dataclass(frozen=True)
class _Relation:
    """``model.name`` read per row: ``kind`` is ``one``, ``many`` or ``""`` (unknown)."""

    model: type[Model] | None
    name: str
    kind: str
    target: type[Model] | None
    #: For a reverse relation, the query name from ``model`` to ``target`` (``booking``).
    query_name: str = ""

    @property
    def label(self) -> str:
        if self.model is None:
            return self.target.__name__ if self.target else "?"
        return f"{self.model.__name__}.{self.name}" if self.name else self.model.__name__


def _forward_paths(model: type[Model], target: type[Model], depth: int = 2) -> list[str]:
    found: list[str] = []
    for item in model._meta.get_fields():
        if not getattr(item, "concrete", False) or not (item.many_to_one or item.one_to_one):
            continue
        if item.related_model is target:
            found.append(item.name)
        elif depth > 1 and isinstance(item.related_model, type):
            found.extend(
                f"{item.name}__{p}" for p in _forward_paths(item.related_model, target, depth - 1)
            )
    return found


def _pick(paths: list[str], instance: Any, params: Any) -> list[str]:
    """Of several FKs to one model, the one whose value is the fetched primary key."""
    if len(paths) < 2 or instance is None or not params:
        return paths
    wanted = str(params[0]).replace("-", "")
    found = []
    for path in paths:
        if "__" in path:
            continue
        attname = type(instance)._meta.get_field(path).attname
        if str(getattr(instance, attname, "")).replace("-", "") == wanted:
            found.append(path)
    return found or paths


def _relation(
    model: type[Model] | None, sql: str, params: Any = None, instance: Any = None
) -> _Relation:
    tables = _tables()
    source = _FROM.search(sql)
    target = tables.get(source["table"]) if source else None
    equals = _EQUALS.search(sql)
    if model is None or target is None or equals is None:
        return _Relation(model, "", "", target)
    table = tables.get(equals["table"])
    column = equals["column"]
    if table is target and column == target._meta.pk.column:
        paths = _pick(_forward_paths(model, target), instance, params)
        return _Relation(model, " or ".join(paths), "one" if paths else "", target)
    if table is not None:
        for item in table._meta.concrete_fields:
            if item.column == column and item.is_relation and item.related_model is model:
                if table._meta.auto_created:  # an M2M through table
                    for m2m in [*model._meta.many_to_many, *model._meta.related_objects]:
                        through = getattr(getattr(m2m, "remote_field", m2m), "through", None)
                        if through is table:
                            name = m2m.name if hasattr(m2m, "attname") else m2m.get_accessor_name()
                            return _Relation(model, str(name), "many", target)
                accessor = item.remote_field.get_accessor_name()
                query_name = item.related_query_name()
                return _Relation(model, str(accessor), "many", target, str(query_name))
    return _Relation(model, "", "", target)


def _filtered(sql: str, relation: _Relation) -> bool:
    """True when the per-row WHERE does more than match the relation (a .filter()/.exclude())."""
    match = _WHERE.search(sql)
    if match is None:
        return False
    where = _EQUALS.sub("", match["where"])
    where = re.sub(r"\"\w+\"\.\"deleted_at\" IS NULL", "", where)
    return bool(re.search(r"=|<|>|\bIN\b|\bLIKE\b|\bNOT\b|\bIS NOT\b", where, re.I))


@dataclass(frozen=True)
class _Context:
    """What the analysis knows about the view that answered."""

    view: Any = None
    action: str = ""
    root_model: type[Model] | None = None
    #: ``(prefix, BlindSpot)`` pairs from :func:`karni.api.optimizer.blind_spots`.
    blind: tuple[tuple[str, Any], ...] = ()
    planned: frozenset[str] = frozenset()
    optimized: bool = True

    @property
    def name(self) -> str:
        return str(getattr(self.view, "__name__", "the viewset"))

    def spot(self, label: str, prefix: str) -> tuple[str, Any] | None:
        """The blind spot for a field label, preferring the one at ``prefix``."""
        found = [(p, spot) for p, spot in self.blind if spot.label == label]
        return next(((p, s) for p, s in found if p == prefix), found[0] if found else None)


def _view_context(target: Target, user: Any) -> _Context:
    from karni.api.viewsets import OPTIMIZED_ACTIONS, BaseViewSet

    view_class = target.view
    if not (isinstance(view_class, type) and issubclass(view_class, BaseViewSet)):
        return _Context(view=view_class, action=target.action)
    try:
        from django.contrib.auth.models import AnonymousUser
        from rest_framework.request import Request
        from rest_framework.test import APIRequestFactory

        from karni.api.optimizer import blind_spots, planned_lookups

        view = view_class()
        view.action = target.action
        view.request = Request(APIRequestFactory().get(target.path))
        view.request.user = user or AnonymousUser()
        view.format_kwarg = None
        view.args, view.kwargs = (), dict(target.kwargs)
        serializer = view.get_serializer_class()
        model = view.get_model()
        context = view.get_serializer_context()
        spots = tuple(blind_spots(serializer, model, context))
        planned = planned_lookups(serializer, model, context)
    except Exception:  # noqa: BLE001 - analysis is best effort; the counts still stand
        logger.debug("karni queries: no plan for %s", view_class, exc_info=True)
        return _Context(view=view_class, action=target.action)
    optimized = bool(view_class.optimize) and target.action in OPTIMIZED_ACTIONS
    return _Context(view_class, target.action, model, spots, planned, optimized)


def _source_of(obj: Any) -> str:
    import inspect

    try:
        path = inspect.getsourcefile(obj)
        _lines, line = inspect.getsourcelines(obj)
    except (OSError, TypeError):
        return ""
    return f"{short_path(path)}:{line}" if path else ""


def _blind_text(spot: Any) -> tuple[str, str]:
    """``(kind label, why)`` for a :class:`~karni.api.optimizer.BlindSpot`."""
    owner = f"{spot.model.__name__}.{spot.attribute}"
    if spot.kind == "method":
        method = getattr(spot.serializer, spot.attribute, None)
        at = _source_of(method) if method is not None else ""
        return (
            f"a SerializerMethodField ({spot.attribute}{', ' + at if at else ''})",
            f"the optimiser treats a SerializerMethodField as opaque and cannot see what "
            f"{spot.attribute}() reads ({_OPTIMIZER})",
        )
    if spot.kind in ("property", "callable"):
        descriptor = getattr(spot.model, spot.attribute, None)
        code = getattr(descriptor, "fget", None) or getattr(descriptor, "func", None) or descriptor
        at = _source_of(code) if code is not None else ""
        what = "a model property" if spot.kind == "property" else "a model method"
        return (
            f"{what}, {owner}{' (' + at + ')' if at else ''}",
            f"the optimiser follows relations, not code, so it cannot see what {owner} reads "
            f"({_OPTIMIZER})",
        )
    if spot.kind == "representation":
        method = getattr(spot.serializer, "to_representation", None)
        at = _source_of(method) if method is not None else ""
        return (
            f"rendered by {spot.serializer.__name__}.to_representation"
            + (f" ({at})" if at else ""),
            "the optimiser walks declared fields only and cannot see what an overridden "
            f"to_representation reads ({_OPTIMIZER})",
        )
    if spot.kind == "object":
        return (
            "a field given the whole object (source='*')",
            f"the optimiser cannot tell which relation such a field reads ({_OPTIMIZER})",
        )
    return (
        f"the attribute {owner}",
        "it is not a model field or relation, so the optimiser has nothing to fetch "
        f"({_OPTIMIZER})",
    )


_CONDITION = re.compile(r"(?P<not>NOT \()?\"(?P<table>\w+)\"\.\"(?P<column>\w+)\" = %s")


def _q_filter(sql: str, params: Any, relation: _Relation) -> str:
    """The per-row WHERE as ``Q(...)`` on the relation (``~Q(booking__status="cancelled")``).

    Only plain equality conditions translate; anything else gives ``Q(...)``.
    """
    match = _WHERE.search(sql)
    if match is None or not relation.query_name or not isinstance(params, list | tuple):
        return "Q(...)"
    where = match["where"]
    offset = sql[: match.start("where")].count("%s")
    target = relation.target
    parts: list[str] = []
    for found in _CONDITION.finditer(where):
        index = offset + where[: found.start()].count("%s")
        if target is None or index >= len(params) or found["table"] != target._meta.db_table:
            return "Q(...)"
        column = found["column"]
        item = next((f for f in target._meta.concrete_fields if f.column == column), None)
        if item is None:
            return "Q(...)"
        if item.is_relation and item.related_model is relation.model:
            continue  # the relation itself
        q = f"Q({relation.query_name}__{item.name}={params[index]!r})"
        parts.append(f"~{q}" if found["not"] else q)
    rest = _CONDITION.sub("", where)
    rest = re.sub(r"\"\w+\"\.\"deleted_at\" IS NULL", "", rest)
    if re.search(r"=|<|>|\bIN\b|\bLIKE\b|\bIS NOT\b", rest, re.I) or not parts:
        return "Q(...)"
    return " & ".join(parts)


def _aggregate_fix(
    sql: str, params: Any, relation: _Relation, prefix: str, ctx: _Context, where: str
) -> str:
    match = _AGGREGATE.search(sql)
    func = (match["func"] if match else "Count").capitalize()
    column = match["column"] if match and match["column"] else ""
    if relation.query_name:
        path = (
            f"{relation.query_name}__{column}"
            if column and func != "Count"
            else relation.query_name
        )
    else:
        path = f"<relation>__{column}" if column else "<relation>"
    name = f"{func.lower()}_{column or 'rows'}"
    filtered = _filtered(sql, relation)
    condition = _q_filter(sql, params, relation) if filtered else ""
    expression = f'{name}={func}("{path}"' + (f", filter={condition}" if filtered else "") + ")"
    same = f" (the filter {where} applies)" if filtered and where and condition == "Q(...)" else ""
    model = relation.model.__name__ if relation.model else "the model"
    render = (
        f'render it from that value: a field with source="{name}" (read_only=True), or compute '
        "from it what the property returned"
    )
    if not prefix:
        return (
            "no prefetch can serve a per-row aggregate; compute it in the list query: override "
            f"get_queryset() on {ctx.name} to return super().get_queryset().annotate("
            f"{expression}){same}, then {render}"
        )
    level = prefix.rstrip("_")
    return (
        "no prefetch can serve a per-row aggregate; annotate it where the "
        f'{model} rows are fetched: prefetch_related = [Prefetch("{level}", queryset='
        f"{model}.objects.annotate({expression}))] on {ctx.name}{same}, then {render}"
    )


@dataclass(frozen=True)
class _Level:
    """Where in the response a field renders: the lookup path to its rows."""

    prefix: str = ""
    #: True when the path crosses a to-many relation (``select_related`` cannot follow it).
    many: bool = False


def _level(fields: tuple[FieldStep, ...]) -> _Level:
    from rest_framework.serializers import ListSerializer

    parts: list[str] = []
    many = False
    outer = fields if fields and fields[-1].inside else fields[:-1]
    for step in outer:
        attrs = [str(attr) for attr in getattr(step.field, "source_attrs", []) or []]
        parts.extend(attrs)
        many = (
            many
            or isinstance(step.field, ListSerializer)
            or bool(getattr(step.field, "many", False))
        )
    return _Level("".join(f"{part}__" for part in parts), many)


def _hint(relation: _Relation, level: _Level, ctx: _Context) -> str:
    name = relation.name.split(" or ")[0] if relation.name else "<relation>"
    to_one = relation.kind == "one"
    attr = "select_related" if to_one else "prefetch_related"
    if not level.prefix:
        return f'{attr} = ["{name}"] on {ctx.name}'
    if to_one and not level.many:
        return f'select_related = ["{level.prefix}{name}"] on {ctx.name}'
    meta = "select" if to_one else "prefetch"
    model = relation.model.__name__ if relation.model else "the model"
    return (
        f'APIMeta.{meta} = ["{name}"] on {model} (applied wherever {model} is rendered, at any '
        f'depth), or prefetch_related = ["{level.prefix}{name}"] on {ctx.name}'
    )


def _spot_for(fields: tuple[FieldStep, ...], level: _Level, ctx: _Context) -> Any | None:
    """The optimiser's blind spot behind the innermost field, if it noted one."""
    from rest_framework.serializers import BaseSerializer, ListSerializer

    if not fields:
        root = ctx.spot(_root_serializer_name(ctx), "")
        return root[1] if root else None
    step = fields[-1]
    found = ctx.spot(step.label, level.prefix)
    if found is not None:
        return found[1]
    serializer = step.field.child if isinstance(step.field, ListSerializer) else step.field
    if isinstance(serializer, BaseSerializer):  # a nested serializer with its own to_representation
        own = ctx.spot(type(serializer).__name__, level.prefix)
        return own[1] if own else None
    return None


def _root_serializer_name(ctx: _Context) -> str:
    roots = [spot for prefix, spot in ctx.blind if not prefix and spot.kind == "representation"]
    return roots[0].label if roots else ""


def _explain(
    sample: TracedQuery, frame: str, ctx: _Context
) -> tuple[_Relation, str, str, str, str]:
    """``(relation, kind, why, fix, summary-suffix)`` for statements one cause repeats."""
    fields, sql = sample.fields, sample.sql
    step = fields[-1] if fields else None
    level = _level(fields)
    prefix = level.prefix
    model = step.model if step is not None else ctx.root_model
    params = sample.params if isinstance(sample.params, list | tuple) else None
    relation = _relation(model, sql, params, step.instance if step is not None else None)
    aggregate = bool(_AGGREGATE.search(sql))
    exists = bool(_EXISTS.search(sql))
    filtered = not aggregate and _filtered(sql, relation)
    suffix = "not prefetched"
    if aggregate:
        suffix = "(an aggregate per row)"
    elif filtered:
        suffix = "(a filtered query per row)"
    elif exists:
        suffix = "(an exists() per row)"
    spot = _spot_for(fields, level, ctx)
    if step is None and spot is None:
        where = frame or "code outside serializer rendering"
        lookup = relation.name or "the relation"
        return (
            relation,
            "code",
            f"{where} runs it once per row, outside serializer rendering, so the optimiser "
            "(which plans for serializers) has no part in it.",
            f'select_related / prefetch_related("{lookup}") on the queryset that loop iterates '
            f"({where})",
            suffix,
        )
    special = ""
    if aggregate:
        special = _aggregate_fix(sql, params, relation, prefix, ctx, frame)
    elif exists or filtered:
        call = ".exists()/.first()" if exists else ".filter()/.exclude()/.order_by()"
        rel = relation.name or "<relation>"
        target = relation.target.__name__ if relation.target else "Model"
        special = (
            f"the code calls {call} on a related manager, which always queries, prefetched or "
            f'not: prefetch the rows it needs (Prefetch("{prefix}{rel}", queryset='
            f'{target}.objects.filter(...), to_attr="{rel.removesuffix("_set")}_selected")) and '
            "read that list in Python"
        )
    if spot is not None:
        kind_label, why = _blind_text(spot)
        fix = special or _hint(relation, level, ctx)
        if spot.kind == "method" and relation.kind == "one" and not special:
            fix += (
                f"; or, if {spot.attribute}() only reads {relation.name}.<attr>, declare "
                f'serializers.CharField(source="{relation.name}.<attr>", read_only=True) '
                f"instead and the optimiser joins {relation.name} itself"
            )
        elif relation.kind == "many" and not special:
            fix += (
                f" (then read it with .all(): .filter() or .count() on {relation.name} "
                "always queries)"
            )
        who = step.label if step is not None else spot.label
        return relation, spot.kind, f"{who} is {kind_label}: {why}.", fix, suffix
    label = step.label if step is not None else ctx.name  # step is set: handled above
    if not ctx.optimized:
        if ctx.view is not None and not getattr(ctx.view, "optimize", True):
            why = (
                f"{ctx.name} sets optimize = False, so only its select_related / "
                "prefetch_related hints apply"
            )
            fix = f"remove optimize = False from {ctx.name}, or add {_hint(relation, level, ctx)}"
        else:
            why = (
                f"the action {ctx.action!r} is not list or retrieve, and custom actions are not "
                "optimised automatically"
            )
            fix = (
                "return self.paginated_response(queryset) from the action (it optimises), or "
                "pass the queryset through self.optimize_queryset(queryset)"
            )
        return relation, "unoptimised", why + ".", special or fix, suffix
    lookup = f"{prefix}{relation.name}" if relation.name else ""
    if lookup and lookup in ctx.planned:
        return (
            relation,
            "refetched",
            f"the optimiser does fetch {lookup} for {label}, yet it ran once per row: the "
            "code re-reads it outside the prefetch.",
            special
            or "read the prefetched rows (.all()) instead of a new query on the related manager",
            suffix,
        )
    return (
        relation,
        "unplanned",
        f"{label} reads {relation.label}, which the optimiser's plan for {ctx.name} does "
        "not include.",
        special or _hint(relation, level, ctx),
        suffix,
    )


def _label(query: TracedQuery) -> str:
    return query.fields[-1].label if query.fields else ""


def analyse(queries: list[TracedQuery], ctx: _Context) -> list[Cause]:
    """Group the repeated statements by cause, most repeated first."""
    by_sql: dict[str, list[TracedQuery]] = {}
    for query in queries:
        if not query.control:
            by_sql.setdefault(query.sql, []).append(query)
    causes: dict[tuple[str, str, str], Cause] = {}
    for sql, group in by_sql.items():
        if len(group) < 2:
            continue
        keys = Counter((_label(q), q.frame or q.karni_frame) for q in group)
        (label, frame), _n = keys.most_common(1)[0]
        sample = next(q for q in group if _label(q) == label)
        relation, kind, why, fix, suffix = _explain(sample, frame, ctx)
        key = (label, relation.label, frame)
        cause = causes.get(key)
        if cause is None:
            cause = causes[key] = Cause(
                count=0,
                summary=f"{relation.label} {suffix}",
                field=label,
                chain=tuple(s.label for s in sample.fields),
                relation=relation.label,
                kind=kind,
                why=why,
                fix=fix,
                where=frame,
            )
        cause.count += len(group)
        cause.statements.append((len(group), sql))
    return sorted(causes.values(), key=lambda cause: -cause.count)


# running


class RequestFailed(Exception):
    """The view raised; ``text`` is the traceback, for the command to explain."""

    def __init__(self, text: str) -> None:
        super().__init__("the view raised an exception")
        self.text = text


def _explain_plans(queries: list[TracedQuery], limit: int = 3) -> list[tuple[str, str]]:
    connection = connections["default"]
    slowest: dict[str, TracedQuery] = {}
    for query in queries:
        if query.control or not query.sql.lstrip().upper().startswith("SELECT"):
            continue
        if query.sql not in slowest or query.duration > slowest[query.sql].duration:
            slowest[query.sql] = query
    picked = sorted(slowest.values(), key=lambda q: -q.duration)[:limit]
    plans: list[tuple[str, str]] = []
    prefix = connection.ops.explain_query_prefix()
    for query in picked:
        try:
            with connection.cursor() as cursor:
                cursor.execute(f"{prefix} {query.sql}", query.params)
                rows = cursor.fetchall()
        except Exception as exc:  # noqa: BLE001 - a plan we cannot get is reported, not raised
            plans.append((query.sql, f"(no plan: {exc})"))
            continue
        plans.append((query.sql, "\n".join(" | ".join(str(c) for c in row) for row in rows)))
    return plans


def run(
    endpoint: str,
    *,
    user: str | None = None,
    method: str = "GET",
    data: str | None = None,
    explain: bool = False,
) -> Report:
    """Request ``endpoint`` as ``user`` and report its queries (see the module docstring).

    :raises KarniLookupError: ``E940`` (endpoint) / ``E941`` (user).
    :raises KarniValueError: ``E942`` (method or data).
    :raises RequestFailed: the view raised; ``.traceback`` holds it.
    """
    from rest_framework.test import APIClient

    method = method.upper()
    if method not in ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"):
        raise KarniValueError(
            f"--method {method}: use GET, POST, PUT, PATCH, DELETE, HEAD or OPTIONS.", code="E942"
        )
    body: Any = None
    if data:
        try:
            body = json.loads(data)
        except json.JSONDecodeError as exc:
            raise KarniValueError(
                f"--data is not JSON ({exc.msg} at character {exc.pos}): pass a JSON object, "
                'e.g. --data \'{"title": "Launch"}\'.',
                code="E942",
            ) from None
    account = resolve_user(user)
    target = resolve_endpoint(endpoint, method, account)
    ctx = _view_context(target, account)
    client = APIClient()
    if account is not None:
        client.force_authenticate(account)
    hosts = [*getattr(settings, "ALLOWED_HOSTS", []), "testserver"]
    plans: list[tuple[str, str]] = []
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)  # the dev query log and request logs would interleave
    try:
        with (
            override_settings(
                KARNI_QUERY_BUDGET_MODE="off", KARNI_API_CACHE=False, ALLOWED_HOSTS=hosts
            ),
            transaction.atomic(),
        ):
            with recording() as recorder:
                started = time.perf_counter()
                try:
                    response = client.generic(
                        method,
                        target.path,
                        json.dumps(body) if body is not None else "",
                        content_type="application/json",
                        secure=bool(getattr(settings, "SECURE_SSL_REDIRECT", False)),
                    )
                except Exception:  # noqa: BLE001 - reported with the failure catalogue
                    raise RequestFailed(traceback.format_exc()) from None
                elapsed = time.perf_counter() - started
            if explain:
                plans = _explain_plans(recorder.traced)
            transaction.set_rollback(True)
    finally:
        logging.disable(previous)
    budget = None
    if ctx.view is not None and hasattr(ctx.view, "get_query_budget") and target.action:
        view = ctx.view()
        view.action = target.action
        budget = view.get_query_budget()
    label = ""
    if account is not None:
        from django.contrib.auth import get_user_model

        label = str(getattr(account, get_user_model().USERNAME_FIELD, account.pk))
    report = Report(
        method=method,
        path=target.path,
        user=label,
        status=response.status_code,
        view=target.label,
        budget=budget,
        queries=recorder.traced,
        causes=analyse(recorder.traced, ctx),
        plans=plans,
    )
    report.notes.extend(_notes(report, account, elapsed, method))
    return report


def _notes(report: Report, account: Any, elapsed: float, method: str) -> list[str]:
    notes = []
    if account is not None:
        notes.append(
            "force-authenticated: a real request also runs its session or token and user "
            "lookups (1-2 queries)."
        )
    if report.status in (401, 403, 404):
        notes.append(
            f"{report.status}: the view refused this request, so these are the access check's "
            "queries, not the response's. "
            f"`karni why {report.path} --as {report.user or 'anonymous'}"
            + ("" if method == "GET" else f" --method {method}")
            + "` explains the decision."
        )
    if method != "GET":
        notes.append("the request's writes were rolled back.")
    notes.append(f"{elapsed * 1000:.0f} ms for the whole request.")
    return notes
