"""Experimental. ``karni queries --explain`` on PostgreSQL: each query's plan, and the scans to fix.

:func:`explain_analyze` runs ``EXPLAIN (ANALYZE, FORMAT JSON)`` for every
distinct ``SELECT`` an endpoint ran, each in a savepoint inside the request's
transaction, which :func:`karni.api.diagnose.run` rolls back: ANALYZE runs
the query, and nothing it does stays. The plan comes back as text (one line
per node, with the actual rows, loops and time) and every sequential scan on
a table of :func:`seq_scan_threshold` rows or more is a :class:`SeqScan`
finding (``W611``) that names the index that would serve its filter or its
sort, as the ``models.Index(...)`` line to add to the model's
``Meta.indexes``, or says why no index would help (the filter keeps most of
the rows).

Only PostgreSQL has ``EXPLAIN ANALYZE`` with a plan Karni reads. On another
database ``karni queries --explain`` keeps its plain ``EXPLAIN`` of the
slowest statements and says so (``W610``).

Override / escape hatch: ``KARNI_EXPLAIN_SEQ_SCAN_ROWS`` sets the row
threshold (default :data:`SEQ_SCAN_ROWS`); :func:`explain_analyze`,
:func:`render_plan` and :func:`suggest_index` are public for other tooling.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any, Final

from django.apps import apps
from django.conf import settings
from django.db import connections, transaction
from django.db.models import Model

__all__ = [
    "SEQ_SCAN_ROWS",
    "Explained",
    "SeqScan",
    "explain_analyze",
    "render_plan",
    "seq_scan_threshold",
    "suggest_index",
]

#: Rows from which a sequential scan is flagged (``KARNI_EXPLAIN_SEQ_SCAN_ROWS``).
SEQ_SCAN_ROWS: Final = 1000
#: A filter that keeps more than this share of the rows is served best by the scan itself.
KEEPS_MOST: Final = 0.5

_COMPARISON = re.compile(
    r"(?P<upper>upper\()?\(*\"?(?P<column>[a-z_][a-z0-9_]*)\"?\)*(?:::[a-z ]+(?:\[\])?)?\)*\s*"
    r"(?P<op>IS NOT NULL|IS NULL|= ANY|<>|<=|>=|=|<|>|~~\*|~~)",
)
_SORT_KEY = re.compile(r"^(?:\"?(?P<table>\w+)\"?\.)?\"?(?P<column>\w+)\"?(?P<desc> DESC)?")


def seq_scan_threshold() -> int:
    """Experimental. ``KARNI_EXPLAIN_SEQ_SCAN_ROWS``, else :data:`SEQ_SCAN_ROWS`."""
    value = getattr(settings, "KARNI_EXPLAIN_SEQ_SCAN_ROWS", None)
    return int(value) if value else SEQ_SCAN_ROWS


@dataclass(frozen=True)
class SeqScan:
    """Experimental. A sequential scan on a large table, and the index that would serve it."""

    table: str
    rows: int
    scanned: int
    kept: int
    sql: str
    filter: str = ""
    sort: tuple[str, ...] = ()
    model: str = ""
    index: str = ""
    why: str = ""
    code: str = "W611"

    def line(self) -> str:
        what = f" for {self.filter}" if self.filter else ""
        if self.sort and not self.filter:
            what = f" for ORDER BY {', '.join(self.sort)}"
        head = (
            f"{self.code} Seq Scan on {self.table} ({self.rows:,} rows, {self.scanned:,} read, "
            f"{self.kept:,} kept){what}"
        )
        if self.index:
            note = f" ({self.why})" if self.why else ""
            return f"{head}: add {self.index} to {self.model}.Meta.indexes{note}"
        return f"{head}: {self.why}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "table": self.table,
            "model": self.model,
            "rows": self.rows,
            "scanned": self.scanned,
            "kept": self.kept,
            "filter": self.filter,
            "sort": list(self.sort),
            "index": self.index,
            "why": self.why,
            "sql": self.sql,
        }


@dataclass
class Explained:
    """Experimental. What :func:`explain_analyze` found: a plan per statement, and the scans."""

    plans: list[tuple[str, str]] = field(default_factory=list)
    scans: list[SeqScan] = field(default_factory=list)


def _nodes(plan: dict[str, Any], parents: tuple[dict[str, Any], ...] = ()) -> Iterator[Any]:
    yield plan, parents
    for child in plan.get("Plans") or ():
        yield from _nodes(child, (*parents, plan))


def render_plan(plan: dict[str, Any]) -> str:
    """Experimental. A JSON plan node as text: one line per node with actual rows, loops, time."""
    lines: list[str] = []
    for node, parents in _nodes(plan):
        indent = "  " * len(parents)
        text = node.get("Node Type", "?")
        if node.get("Relation Name"):
            text += f" on {node['Relation Name']}"
        if node.get("Index Name"):
            text += f" using {node['Index Name']}"
        if "Actual Rows" in node:
            text += (
                f" (actual rows={node['Actual Rows']} loops={node.get('Actual Loops', 1)} "
                f"time={node.get('Actual Total Time', 0):.3f}ms)"
            )
        lines.append(indent + text)
        for key in ("Index Cond", "Filter", "Sort Key", "Join Filter", "Hash Cond"):
            value = node.get(key)
            if value:
                shown = ", ".join(value) if isinstance(value, list) else value
                lines.append(f"{indent}  {key}: {shown}")
        removed = node.get("Rows Removed by Filter")
        if removed:
            lines.append(f"{indent}  Rows Removed by Filter: {removed}")
    return "\n".join(lines)


def _table_rows(alias: str, table: str) -> int:
    """The table's rows: PostgreSQL's estimate, counted exactly when it is small or unknown."""
    connection = connections[alias]
    threshold = seq_scan_threshold()
    with connection.cursor() as cursor:
        cursor.execute("SELECT reltuples FROM pg_class WHERE relname = %s", [table])
        found = cursor.fetchone()
        estimate = int(found[0]) if found and found[0] is not None else -1
        if estimate >= threshold * 10:
            return estimate
        quoted = connection.ops.quote_name(table)
        cursor.execute(f"SELECT COUNT(*) FROM {quoted}")  # noqa: S608 - a quoted table name
        return int(cursor.fetchone()[0])


def _model_for(table: str) -> type[Model] | None:
    return next(
        (m for m in apps.get_models(include_auto_created=True) if m._meta.db_table == table), None
    )


def _field_name(model: type[Model], column: str) -> str | None:
    for model_field in model._meta.concrete_fields:
        if model_field.column == column:
            return str(model_field.name)
    return None


def _index_name(model: type[Model], names: Iterable[str]) -> str:
    """A name Django accepts (30 characters at most) that says what the index covers."""
    stem = f"{model._meta.model_name}_{'_'.join(n.lstrip('-') for n in names)}"
    if len(stem) + 4 <= 30:
        return f"{stem}_idx"
    digest = hashlib.sha1(stem.encode()).hexdigest()[:6]
    return f"{stem[:19]}_{digest}_ix"[:30]


def _existing_index(alias: str, table: str, columns: list[str]) -> str | None:
    """The name of an index on ``table`` whose first column is ``columns[0]``."""
    connection = connections[alias]
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, table)
    for name, info in constraints.items():
        if (info.get("index") or info.get("unique")) and info.get("columns")[:1] == columns[:1]:
            return str(name)
    return None


def suggest_index(
    model: type[Model] | None, filter_text: str, sort: Iterable[str] = ()
) -> tuple[str, str]:
    """Experimental. ``(index, why)``: the ``models.Index(...)`` that serves a scan, or why not.

    Equality columns first (in the filter's order), then one range column;
    with no usable filter, a ``LIKE`` (``icontains``, search) asks for a
    trigram index, then the sort keys. ``deleted_at IS NULL`` (soft delete)
    becomes the index's ``condition``.
    """
    if model is None:
        return "", "the table belongs to no model of the project"
    equal: list[str] = []
    ranges: list[str] = []
    like: list[str] = []
    upper = False
    partial: list[str] = []
    for match in _COMPARISON.finditer(filter_text):
        name = _field_name(model, match["column"])
        if name is None:
            continue
        op = match["op"]
        if op in ("=", "= ANY") and name not in equal:
            equal.append(name)
        elif op in ("<", ">", "<=", ">=") and name not in ranges:
            ranges.append(name)
        elif op.startswith("~~") and name not in like:
            like.append(name)
            upper = upper or bool(match["upper"])
        elif op == "IS NULL" and name not in partial:
            partial.append(name)
    condition = ""
    if partial:
        condition = ", condition=Q(" + ", ".join(f"{n}__isnull=True" for n in partial) + ")"
    names = equal + ranges[:1]
    if not names and like:
        index = _index_name(model, [like[0], "trgm"])
        if upper:  # icontains: UPPER(column) LIKE UPPER(...), so the index is on UPPER(column)
            return (
                f'GinIndex(OpClass(Upper("{like[0]}"), name="gin_trgm_ops"), name="{index}"'
                f"{condition})",
                "GinIndex and OpClass come from django.contrib.postgres, Upper from "
                "django.db.models.functions, and the index needs the pg_trgm extension",
            )
        return (
            f'GinIndex(fields=["{like[0]}"], opclasses=["gin_trgm_ops"], name="{index}"'
            f"{condition})",
            "GinIndex comes from django.contrib.postgres.indexes, and the index needs the "
            "pg_trgm extension",
        )
    if not names:
        for key in sort:
            found = _SORT_KEY.match(key.strip())
            if found and (name := _field_name(model, found["column"])):
                names.append(f"-{name}" if found["desc"] else name)
    if not names:
        return "", "no column of the filter can lead an index"
    fields = ", ".join(f'"{name}"' for name in names)
    return f'models.Index(fields=[{fields}], name="{_index_name(model, names)}"{condition})', ""


def _scan(
    node: dict[str, Any], parents: tuple[dict[str, Any], ...], sql: str, alias: str
) -> SeqScan | None:
    table = node.get("Relation Name")
    if node.get("Node Type") != "Seq Scan" or not table:
        return None
    loops = int(node.get("Actual Loops") or 1)
    kept = int(node.get("Actual Rows") or 0) * loops
    scanned = kept + int(node.get("Rows Removed by Filter") or 0) * loops
    rows = _table_rows(alias, table)
    if rows < seq_scan_threshold():
        return None
    filter_text = str(node.get("Filter") or "")
    sort: tuple[str, ...] = ()
    for parent in reversed(parents):
        if parent.get("Sort Key"):
            sort = tuple(str(key) for key in parent["Sort Key"])
            break
    model = _model_for(table)
    label = model.__name__ if model is not None else table
    if filter_text and scanned and kept / scanned > KEEPS_MOST and not sort:
        return SeqScan(
            table, rows, scanned, kept, sql, filter_text, sort, label,
            why=f"the filter keeps {kept / scanned:.0%} of the rows read, so reading the table is "
            "the right plan: narrow the filter or paginate",
        )  # fmt: skip
    index, why = suggest_index(model, filter_text, sort)
    if index:
        columns = [
            m["column"]
            for m in _COMPARISON.finditer(filter_text)
            if m["op"] in ("=", "= ANY", "<", ">", "<=", ">=")
        ]
        existing = _existing_index(alias, table, columns) if columns else None
        if existing:
            index, why = (
                "",
                (
                    f"the index {existing} covers {columns[0]} and the planner read the table "
                    f"anyway: run ANALYZE {table}, or the filter matches too many rows"
                ),
            )
    return SeqScan(table, rows, scanned, kept, sql, filter_text, sort, label, index, why)


def explain_analyze(queries: Iterable[Any], *, alias: str = "default") -> Explained:
    """Experimental. ``EXPLAIN (ANALYZE, FORMAT JSON)`` of each distinct ``SELECT`` of ``queries``.

    ``queries`` carry ``sql``, ``params`` and ``control``
    (:class:`karni.api.diagnose.TracedQuery`). Each runs in a savepoint, so a
    statement that fails to explain is reported and the others still run.
    Call it inside a transaction that is rolled back.
    """
    connection = connections[alias]
    result = Explained()
    seen: set[str] = set()
    for query in queries:
        sql = query.sql
        if query.control or sql in seen:
            continue
        if not sql.lstrip().upper().startswith(("SELECT", "WITH")):
            continue
        seen.add(sql)
        try:
            with transaction.atomic(using=alias), connection.cursor() as cursor:
                cursor.execute(f"EXPLAIN (ANALYZE, FORMAT JSON) {sql}", query.params)
                raw = cursor.fetchone()[0]
        except Exception as exc:  # noqa: BLE001 - a plan we cannot get is reported, not raised
            result.plans.append((sql, f"(no plan: {exc})"))
            continue
        document = json.loads(raw) if isinstance(raw, str) else raw
        top = document[0]
        plan = top["Plan"]
        text = render_plan(plan)
        if "Execution Time" in top:
            text += f"\nExecution Time: {top['Execution Time']:.3f}ms"
        result.plans.append((sql, text))
        for node, parents in _nodes(plan):
            found = _scan(node, parents, sql, alias)
            if found is None:
                continue
            key = (found.table, found.filter, found.index or found.why)
            if all((s.table, s.filter, s.index or s.why) != key for s in result.scans):
                result.scans.append(found)
    return result
