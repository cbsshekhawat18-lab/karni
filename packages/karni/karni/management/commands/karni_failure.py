"""``manage.py karni_failure <id>`` — a failure snapshot as a brief (``karni explain --failure``).

Accepts a failure id, the id of a request that failed, or ``last``. Prints
who requested what, where it failed (the first project or Karni frame with
its locals), the exception and its Karni code, the queries and the next
steps; ``--json`` prints the whole snapshot.

Override / escape hatch: :func:`karni.debug.brief.resolve_failure` and
:func:`karni.debug.brief.render` are the importable equivalents.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandParser


class Command(BaseCommand):
    help = "Explain a captured failure: request, user, where it failed, SQL, next steps."
    requires_system_checks: list[Any] = []

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("failure_id", help="A failure id, a failed request's id, or `last`.")
        parser.add_argument("--json", action="store_true", help="Print the whole snapshot.")

    def handle(self, *args: Any, **options: Any) -> None:
        from karni.debug.brief import render, resolve_failure
        from karni.debug.store import dumps

        snapshot = resolve_failure(options["failure_id"])
        self.stdout.write(dumps(snapshot, indent=2) if options["json"] else render(snapshot))
