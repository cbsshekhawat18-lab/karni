"""``manage.py karni_schedules`` — every merged beat schedule (``karni schedule``).

Lists what beat will run: every ``<app>/schedules.py`` declaration
(:mod:`karni.schedule`) merged with the ``CELERY_BEAT_SCHEDULE`` setting —
the settings entry wins on a name conflict and its row says which declaration
it overrides. Columns: name, task, timing, source. ``--json`` prints the rows
as a JSON list (with args/kwargs). ``--run NAME`` executes that schedule's task
once, synchronously, in this process (no broker or worker needed) and exits
non-zero if it raised.

Override / escape hatch: :func:`karni.schedule.describe_schedules` and
:func:`karni.schedule.run_schedule` are the importable equivalents.
"""

from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from karni.exceptions import KarniCommandError
from karni.schedule import ScheduleError, describe_schedules, run_schedule

_COLUMNS = ("name", "task", "timing", "source")


def format_table(rows: list[dict[str, Any]]) -> str:
    """Fixed-width NAME/TASK/TIMING/SOURCE table."""
    cells = []
    for row in rows:
        source = row["source"]
        if row["overrides"]:
            source = f"{source} (overrides {row['overrides']})"
        cells.append([row["name"], row["task"], row["timing"], source])
    header = [column.upper() for column in _COLUMNS]
    widths = [max(len(line[i]) for line in [header, *cells]) for i in range(len(_COLUMNS))]
    return "\n".join(
        "  ".join(text.ljust(width) for text, width in zip(line, widths, strict=True)).rstrip()
        for line in [header, *cells]
    )


class Command(BaseCommand):
    help = "List every merged Celery beat schedule, or --run one once synchronously."
    # Listing must work even when system checks fail; `karni check` owns checks.
    requires_system_checks: list[Any] = []

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--json", action="store_true", help="Print rows as a JSON list.")
        parser.add_argument(
            "--run",
            metavar="NAME",
            help="Execute the named schedule's task once, synchronously, with its args.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if options["run"]:
            self._run(options["run"])
            return
        try:
            rows = describe_schedules()
        except ScheduleError as exc:
            raise KarniCommandError(exc.message, code=exc.code) from None
        if options["json"]:
            self.stdout.write(json.dumps(rows, indent=2, default=str))
        elif rows:
            self.stdout.write(format_table(rows))
        else:
            self.stdout.write("No schedules. Declare them in <app>/schedules.py (karni.schedule).")

    def _run(self, name: str) -> None:
        try:
            result = run_schedule(name)
        except ScheduleError as exc:
            raise KarniCommandError(exc.message, code=exc.code) from None
        if result.failed():
            if result.traceback:
                self.stderr.write(str(result.traceback))
            raise KarniCommandError(f"Schedule {name!r} failed: {result.result!r}", code="E408")
        self.stdout.write(f"Ran {name}: {result.result!r}")
