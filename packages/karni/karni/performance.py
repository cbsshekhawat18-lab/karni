"""Query accounting shared by query budgets, the dev query log and ``karni.testing``.

One recorder, three consumers (ADR 0001, Decision 3):

* :class:`karni.api.viewsets.BaseViewSet` wraps every request in
  :func:`record_queries` and compares the count with the action's **query
  budget** (:class:`Budget`, ``KARNI_QUERY_BUDGET``). What happens on an
  overrun is ``KARNI_QUERY_BUDGET_MODE``: ``"raise"`` (tests — the
  ``karni.testing`` pytest plugin sets it), ``"warn"`` (the dev profile: a log
  line plus the ``X-Karni-Queries`` header) or ``"off"`` (production: no
  wrapper at all).
* :class:`karni.middleware.QueryLogMiddleware` prints every request's query
  count, SQL time and grouped duplicates in development.
* :func:`karni.testing.performance.query_budget` asserts a maximum around any
  block of code.

Duplicates are grouped by their SQL text (parameters are not part of it), so
an N+1 shows up as one line — ``12× SELECT … FROM "app_tag" …`` — together
with where it came from: the serializer field that was rendering
(``EventSerializer.tags``) and, when project code ran inside it, the project
frame (``myapp/serializers.py:42 in get_tag_names``).

Override / escape hatches: ``KARNI_QUERY_BUDGET`` (partial dict merged over
:data:`DEFAULT_QUERY_BUDGET`), ``KARNI_QUERY_BUDGET_MODE``, and per viewset
``query_budget = Budget(list=25, reason="...")``.
"""

from __future__ import annotations

import logging
import re
import sys
import sysconfig
import time
from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import Any, Final

from django.conf import settings

from karni.exceptions import KarniAssertionError, KarniImproperlyConfigured

__all__ = [
    "BUDGET_MODES",
    "DEFAULT_QUERY_BUDGET",
    "Budget",
    "QueryBudgetExceeded",
    "QueryGroup",
    "QueryRecorder",
    "QueryReport",
    "RecordedQuery",
    "budget_mode",
    "budget_limits",
    "field_label",
    "is_project_frame",
    "record_queries",
    "rendering_field",
    "short_path",
    "short_sql",
]

logger = logging.getLogger("karni.performance")

DEFAULT_QUERY_BUDGET: Final[Mapping[str, int]] = {
    "list": 8,
    "retrieve": 8,
    "create": 12,
    "update": 12,
    "partial_update": 12,
    "destroy": 10,
    "*": 15,
}
"""Per-action query budgets (ADR 0001 Q3.3); ``"*"`` covers every other action.

``list``/``retrieve`` = 8 covers authentication (1–2), a role lookup (1), the
pagination ``COUNT`` (1), the rows (1) and about three prefetches.
"""

BUDGET_MODES: Final[tuple[str, ...]] = ("raise", "warn", "off")
"""Accepted ``KARNI_QUERY_BUDGET_MODE`` values."""

_SELECT_LIST = re.compile(r"^SELECT\s+(?:DISTINCT\s+)?.+?\sFROM\s", re.IGNORECASE | re.DOTALL)
_FROM_TABLE = re.compile(r"\sFROM\s+[\"`\[]?([\w.]+)", re.IGNORECASE)


# recording


@dataclass(frozen=True)
class RecordedQuery:
    """One executed statement: SQL text (with placeholders), seconds, origin."""

    sql: str
    duration: float
    origin: str = ""


class QueryRecorder:
    """A ``connection.execute_wrapper`` that records every statement it sees.

    The origin of a statement (serializer field and/or project frame) is
    captured the first time its SQL text repeats — the moment it becomes a
    duplicate — so the common no-duplicate path costs one ``Counter`` update.
    """

    def __init__(self) -> None:
        self.queries: list[RecordedQuery] = []
        self._seen: Counter[str] = Counter()

    def __call__(
        self,
        execute: Callable[..., Any],
        sql: str,
        params: Any,
        many: bool,
        context: Mapping[str, Any],
    ) -> Any:
        start = time.perf_counter()
        try:
            return execute(sql, params, many, context)
        finally:
            duration = time.perf_counter() - start
            self._seen[sql] += 1
            origin = query_origin() if self._seen[sql] == 2 else ""
            self.queries.append(RecordedQuery(sql, duration, origin))

    @property
    def count(self) -> int:
        """Number of statements executed so far."""
        return len(self.queries)

    def report(self) -> QueryReport:
        """A grouped, printable view of what was recorded."""
        return QueryReport(tuple(self.queries))


@contextmanager
def record_queries(using: str | None = None) -> Iterator[QueryRecorder]:
    """Record every query run inside the block (all connections, or ``using``).

    ``with record_queries() as recorder: ...`` — then ``recorder.count`` and
    ``recorder.report()``. Recorders nest: each wrapper sees every statement.
    """
    from django.db import connections

    recorder = QueryRecorder()
    aliases = [using] if using else list(connections)
    with ExitStack() as stack:
        for alias in aliases:
            stack.enter_context(connections[alias].execute_wrapper(recorder))
        yield recorder


# origins


def _framework_roots() -> tuple[str, ...]:
    import django
    import rest_framework

    import karni

    stdlib = sysconfig.get_paths()["stdlib"]
    roots = {
        str(Path(django.__file__).parent),
        str(Path(rest_framework.__file__).parent),
        str(Path(karni.__file__).parent),
        stdlib,
        # Homebrew and pyenv put a symlink on the stdlib path; frames name the real file.
        str(Path(stdlib).resolve()),
    }
    roots.update(path for path in sys.path if "site-packages" in path or "dist-packages" in path)
    return tuple(sorted(roots))


_ROOTS: tuple[str, ...] | None = None


def is_project_frame(frame: FrameType) -> bool:
    """True for a frame of project code (not Django, DRF, Karni, the stdlib or site-packages)."""
    global _ROOTS
    if _ROOTS is None:
        _ROOTS = _framework_roots()
    filename = frame.f_code.co_filename
    return not filename.startswith("<") and not filename.startswith(_ROOTS)


def short_path(filename: str) -> str:
    """``filename`` relative to ``BASE_DIR`` (else the working directory) when inside it."""
    base = getattr(settings, "BASE_DIR", None) or Path.cwd()
    try:
        return str(Path(filename).resolve().relative_to(Path(base).resolve()))
    except ValueError:
        return filename


def rendering_field(frame: FrameType) -> Any | None:
    """The DRF field ``frame`` is rendering a value for (a named field of a serializer), else None.

    Matches ``to_representation`` / ``get_attribute`` frames of a bound
    field; top-level and list-child serializers have no name and are skipped.
    """
    if frame.f_code.co_name not in {"to_representation", "get_attribute"}:
        return None
    from rest_framework.fields import Field

    field = frame.f_locals.get("self")
    if not isinstance(field, Field):
        return None
    if not getattr(field, "field_name", None) or getattr(field, "parent", None) is None:
        return None
    return field


def field_label(field: Any) -> str:
    """``Parent.field`` for a bound DRF field (``EventSerializer.tags``)."""
    return f"{type(field.parent).__name__}.{field.field_name}"


def _field_label(frame: FrameType) -> str:
    """``Parent.field`` when ``frame`` is a DRF field rendering a value, else ``""``."""
    field = rendering_field(frame)
    return field_label(field) if field is not None else ""


def query_origin() -> str:
    """Where the statement being executed comes from, as one short string.

    Walks outward from the database call: the innermost DRF field that was
    rendering (``EventSerializer.tags``) and any project frame *inside* it
    (a ``SerializerMethodField`` method, a model property). Without a field,
    the innermost project frame (a view, a service).
    """
    frame: FrameType | None = sys._getframe(1)
    inner_project = ""
    while frame is not None:
        label = _field_label(frame)
        if label:
            return f"{label} ({inner_project})" if inner_project else label
        if not inner_project and is_project_frame(frame):
            code = frame.f_code
            inner_project = f"{short_path(code.co_filename)}:{frame.f_lineno} in {code.co_name}"
        frame = frame.f_back
    return inner_project


# reporting


def short_sql(sql: str, width: int = 140) -> str:
    text = " ".join(sql.split())
    text = _SELECT_LIST.sub(lambda m: "SELECT … FROM ", text, count=1)
    return text if len(text) <= width else text[: width - 1] + "…"


@dataclass(frozen=True)
class QueryGroup:
    """Statements sharing one SQL text."""

    sql: str
    count: int
    duration: float
    origin: str

    @property
    def table(self) -> str:
        """The first table after ``FROM`` (``""`` when there is none)."""
        match = _FROM_TABLE.search(self.sql)
        return match.group(1) if match else ""


@dataclass(frozen=True)
class QueryReport:
    """Recorded statements, grouped so an N+1 reads as one line."""

    queries: tuple[RecordedQuery, ...]

    @property
    def count(self) -> int:
        return len(self.queries)

    @property
    def duration(self) -> float:
        """Total seconds spent in the database."""
        return sum(query.duration for query in self.queries)

    def groups(self) -> list[QueryGroup]:
        """Every distinct SQL text, most repeated first."""
        counts: Counter[str] = Counter()
        durations: dict[str, float] = {}
        origins: dict[str, str] = {}
        for query in self.queries:
            counts[query.sql] += 1
            durations[query.sql] = durations.get(query.sql, 0.0) + query.duration
            if query.origin and query.sql not in origins:
                origins[query.sql] = query.origin
        return [
            QueryGroup(sql, count, durations[sql], origins.get(sql, ""))
            for sql, count in counts.most_common()
        ]

    def duplicates(self) -> list[QueryGroup]:
        """Groups that ran more than once (the N+1 suspects)."""
        return [group for group in self.groups() if group.count > 1]

    def summary(self) -> str:
        """``14 queries, 12 duplicated, 3.2 ms in SQL``."""
        duplicated = sum(group.count for group in self.duplicates())
        return (
            f"{self.count} queries, {duplicated} duplicated, {self.duration * 1000:.1f} ms in SQL"
        )

    def render(self, limit: int = 5) -> str:
        """Summary line plus one line per duplicate group (most repeated first)."""
        lines = [self.summary()]
        duplicates = self.duplicates()
        for group in duplicates[:limit]:
            lines.append(f"  {group.count}× {short_sql(group.sql)}")
            if group.origin:
                lines.append(f"      ← {group.origin}")
        if len(duplicates) > limit:
            lines.append(f"  … {len(duplicates) - limit} more duplicate groups")
        return "\n".join(lines)


# budgets


class QueryBudgetExceeded(KarniAssertionError):
    """A request (or a ``query_budget`` block) ran more queries than its budget.

    An ``AssertionError`` so a test that trips it fails like any assertion.
    """

    code = "E117"


_UNSET: Final = object()


@dataclass(frozen=True, init=False)
class Budget:
    """``query_budget = Budget(list=25, reason="...")`` — a viewset's own query budgets.

    Keyword per action (``list``, ``retrieve``, ``create``, ``update``,
    ``partial_update``, ``destroy`` or a custom ``@action`` name), plus
    ``default=`` for every action not named. A value is a positive integer,
    or ``None`` to stop checking that action. Actions not named keep the
    project budget (``KARNI_QUERY_BUDGET``). ``reason`` is mandatory: a
    budget is a declared exception, listed by ``karni context``.
    """

    limits: Mapping[str, int | None]
    reason: str

    def __init__(self, *, reason: str, default: Any = _UNSET, **actions: int | None) -> None:
        if not isinstance(reason, str) or not reason.strip():
            raise KarniImproperlyConfigured(
                'Budget(..., reason="...") needs a non-empty reason saying why this viewset '
                "needs a different query budget (e.g. reason='per-row signed URLs, measured').",
                code="E115",
            )
        limits: dict[str, int | None] = dict(actions)
        if default is not _UNSET:
            limits["*"] = default
        if not limits:
            raise KarniImproperlyConfigured(
                "Budget() names no action; write e.g. Budget(list=25, reason='...').", code="E115"
            )
        for action, value in limits.items():
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value <= 0
            ):
                raise KarniImproperlyConfigured(
                    f"Budget({action}={value!r}) must be a positive integer, or None to stop "
                    "checking that action.",
                    code="E115",
                )
        object.__setattr__(self, "limits", limits)
        object.__setattr__(self, "reason", reason)

    def limit_for(self, action: str) -> Any:
        """The declared limit for ``action`` (its own, else ``default``), else ``_UNSET``."""
        if action in self.limits:
            return self.limits[action]
        return self.limits.get("*", _UNSET)

    def describe(self) -> str:
        """``list=25, *=None`` — for ``karni context``."""
        return ", ".join(f"{action}={value}" for action, value in self.limits.items())


def budget_limits() -> dict[str, int]:
    """``KARNI_QUERY_BUDGET`` merged over :data:`DEFAULT_QUERY_BUDGET`."""
    configured = getattr(settings, "KARNI_QUERY_BUDGET", None) or {}
    return {**DEFAULT_QUERY_BUDGET, **configured}


def budget_mode() -> str:
    """The active ``KARNI_QUERY_BUDGET_MODE`` (``"off"`` when unset)."""
    mode = getattr(settings, "KARNI_QUERY_BUDGET_MODE", "off") or "off"
    if mode not in BUDGET_MODES:
        raise KarniImproperlyConfigured(
            f"KARNI_QUERY_BUDGET_MODE = {mode!r}; expected one of {', '.join(BUDGET_MODES)}.",
            code="E118",
        )
    return str(mode)


def resolve_budget(declared: Budget | None, action: str | None) -> int | None:
    """The budget for ``action``: the viewset's :class:`Budget`, else the settings."""
    name = action or "*"
    if declared is not None:
        limit = declared.limit_for(name)
        if limit is not _UNSET:
            return limit  # type: ignore[no-any-return]
    limits = budget_limits()
    return limits.get(name, limits["*"])


def budget_failure(label: str, report: QueryReport, limit: int, fix: str) -> str:
    """The message of a budget overrun: what, how many, the duplicates, the fix."""
    return f"{label} ran {report.count} queries; budget is {limit}.\n{report.render()}\n{fix}"
