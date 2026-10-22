"""``manage.py karni_schema``: columns, constraints and indexes per model, and why.

``karni schema`` wraps it.

For each model of the project's own apps (or the ``app`` / ``app.Model``
labels given): every column with its database type and the declaration
behind it; every constraint and index with its SQL, the reason it exists
and, when the table exists, whether the database has it; the columns routed
viewsets search, filter or order by, with the index serving each; and the
database objects no declaration explains. ``--json`` prints the same data
for agents. ``--no-db`` reports the declarations without reading the
database.

Override / escape hatch: :func:`karni.fields.schema.describe` builds the
same report for code.
"""

from __future__ import annotations

import json
from typing import Any

from django.apps import apps
from django.core.management.base import BaseCommand, CommandParser
from django.db import models

from karni.exceptions import KarniCommandError
from karni.fields.schema import ModelSchema, describe_all

__all__ = ["Command"]

_STATUS = {"present": "ok", "missing": "MISSING", "skipped": "skipped", "unknown": ""}


def _resolve(labels: list[str]) -> list[type[models.Model]]:
    if not labels:
        from karni.testing._source import project_app_configs

        return [
            model
            for config in project_app_configs(infer_root=True)
            for model in config.get_models()
            if not (model._meta.proxy or not model._meta.managed)
        ]
    chosen: list[type[models.Model]] = []
    for label in labels:
        try:
            if "." in label:
                chosen.append(apps.get_model(label))
            else:
                chosen.extend(apps.get_app_config(label).get_models())
        except LookupError as exc:
            raise KarniCommandError(
                f"karni schema {label}: no such app or model ({exc}). Pass an app label "
                "(events) or app.Model (events.Event); `karni context` lists them.",
                code="E969",
            ) from exc
    return chosen


def render(report: ModelSchema) -> str:
    """One model's report as aligned text."""
    lines = [f"{report.label}  (table {report.table}, {report.vendor})"]
    width = max((len(c.name) for c in report.columns), default=4)
    type_width = max((len(c.type) for c in report.columns), default=4)
    lines.append("  columns")
    for column in report.columns:
        null = "null" if column.null else "not null"
        lines.append(
            f"    {column.name:<{width}}  {column.type:<{type_width}}  {null:<8}  {column.why}"
        )
    if report.objects:
        lines.append("  constraints and indexes")
        for item in report.objects:
            status = _STATUS.get(item.status, item.status)
            flag = f"[{status}] " if status else ""
            lines.append(f"    {flag}{item.kind} {item.name}")
            lines.append(f"        {item.definition}")
            lines.append(f"        why: {item.why}")
    if report.usage:
        lines.append("  declared usage")
        for row in report.usage:
            served = f"served by {row.covered_by}" if row.covered_by else f"NOT INDEXED: {row.fix}"
            lines.append(f"    {row.declared_by}: {row.kind} {row.field} -> {served}")
    if report.unexplained:
        lines.append("  in the database, not declared")
        lines.extend(f"    {item}" for item in report.unexplained)
    if not report.introspected:
        lines.append("  (database not read: table missing, --no-db, or no connection)")
    return "\n".join(lines)


class Command(BaseCommand):
    help = "Columns, constraints and indexes per model, with the declaration behind each."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("labels", nargs="*", help="app labels or app.Model (default: yours)")
        parser.add_argument("--json", action="store_true", help="Print the report as JSON.")
        parser.add_argument("--database", default="default", help="Database alias to describe.")
        parser.add_argument(
            "--no-db", action="store_true", help="Report declarations only; do not query."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        chosen = _resolve(list(options["labels"]))
        reports = describe_all(chosen, using=options["database"], introspect=not options["no_db"])
        if options["json"]:
            self.stdout.write(json.dumps([r.as_dict() for r in reports], indent=2))
            return
        if not reports:
            self.stdout.write("No models (pass app labels, e.g. karni schema events).")
            return
        self.stdout.write("\n\n".join(render(report) for report in reports))
