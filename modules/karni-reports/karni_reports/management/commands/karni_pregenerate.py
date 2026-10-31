"""``manage.py karni_pregenerate <report>`` (experimental): render a report ahead of requests.

Renders the report for every row its ``get_queryset()`` returns, for the
rows ``--ids`` names, or with ``--stale`` only for the rows whose last file
is out of date (the row or the template changed since). A row whose file is
current counts as cached and is not rendered again, unless ``--force``.
It works in batches of ``--batch-size`` rows (in key order), renders inline
in this process (no worker needed) and prints the counts and the time of
each batch and of the whole run. ``--list`` prints the registered reports.

Override / escape hatch: ``Report.get_queryset`` decides the rows, and
:func:`karni_reports.services.render` is the importable form of one render.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandParser
from karni.exceptions import KarniCommandError, KarniLookupError

from karni_reports import services
from karni_reports.models import GeneratedReport
from karni_reports.registry import get_report, reports
from karni_reports.report import Report


@dataclass
class Counts:
    rows: int = 0
    rendered: int = 0
    cached: int = 0
    failed: int = 0

    def add(self, other: Counts) -> None:
        self.rows += other.rows
        self.rendered += other.rendered
        self.cached += other.cached
        self.failed += other.failed

    def text(self) -> str:
        return (
            f"{self.rows} rows, {self.rendered} rendered, {self.cached} cached, "
            f"{self.failed} failed"
        )


class Command(BaseCommand):
    help = (
        "Experimental. Render a report ahead of requests: for every row, given ids, or only "
        "stale ones, in batches, with counts and times."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("report", nargs="?", help="The report's name (see --list).")
        parser.add_argument("--list", action="store_true", dest="list_reports")
        which = parser.add_mutually_exclusive_group()
        which.add_argument("--ids", nargs="+", metavar="ID", help="Only these rows.")
        which.add_argument(
            "--stale",
            action="store_true",
            help="Only rows rendered before whose file is out of date.",
        )
        parser.add_argument(
            "--force", action="store_true", help="Render even when the file is current."
        )
        parser.add_argument("--batch-size", type=int, default=100, metavar="N")

    def handle(self, *args: Any, **options: Any) -> None:
        if options["list_reports"]:
            for name, report in reports().items():
                model = report.get_model()._meta.label
                self.stdout.write(f"{name}  {model}  {report.get_template_name()}")
            return
        name = options["report"]
        if not name:
            raise KarniCommandError(
                "Name the report to pre-generate. `manage.py karni_pregenerate --list` prints "
                "them.",
                code="REPORT001",
            )
        try:
            report = get_report(name)
        except KarniLookupError as exc:
            raise KarniCommandError(exc.message, code="REPORT001") from exc
        size = max(1, int(options["batch_size"]))
        queryset = report.get_queryset().order_by("pk")
        if options["ids"]:
            queryset = queryset.filter(pk__in=options["ids"])
        if options["stale"]:
            queryset = queryset.filter(pk__in=list(self._rendered_ids(report)))
        started = time.monotonic()
        total = Counts()
        last: Any = None
        number = 0
        while True:
            page = queryset if last is None else queryset.filter(pk__gt=last)
            batch = list(page[:size])
            if not batch:
                break
            number += 1
            began = time.monotonic()
            counts = self._batch(report, batch, force=options["force"])
            total.add(counts)
            last = batch[-1].pk
            self.stdout.write(f"batch {number}: {counts.text()} in {time.monotonic() - began:.1f}s")
        self.stdout.write(f"{report.name}: {total.text()} in {time.monotonic() - started:.1f}s")

    def _rendered_ids(self, report: Report) -> Any:
        content_type = ContentType.objects.get_for_model(report.get_model())
        return (
            GeneratedReport.objects.filter(report=report.name, content_type=content_type)
            .values_list("object_id", flat=True)
            .distinct()
        )

    def _batch(self, report: Report, rows: list[Any], *, force: bool) -> Counts:
        counts = Counts(rows=len(rows))
        for obj in rows:
            key = services.key_for(report, obj)
            row = services.find(key)
            if row is not None and row.is_ready and not force:
                counts.cached += 1
                continue
            if row is None:
                row = GeneratedReport.objects.create(**key.lookup(), template=key.template)
            row.status = GeneratedReport.Status.RENDERING
            row.save(update_fields=["status", "updated_at"])
            done = services.render(row, report=report, obj=obj)
            if done.status == GeneratedReport.Status.READY:
                counts.rendered += 1
            else:
                counts.failed += 1
        return counts
