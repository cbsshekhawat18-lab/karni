"""``manage.py karni_queries ENDPOINT --as USER`` — every query an endpoint runs, and why.

``karni queries`` runs this in the project's interpreter. The work is
:func:`karni.api.diagnose.run`: one in-process request (writes rolled back),
every SQL statement with the stack that issued it, the repeated ones grouped
by cause with the optimiser's reason and the fix. ``--json`` for agents,
``--explain`` adds EXPLAIN plans for the slowest statements, ``--all`` lists
every statement.

Override / escape hatch: call :func:`karni.api.diagnose.run` from your own
tooling for a different report.
"""

from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from karni.exceptions import KarniCommandError, KarniError


class Command(BaseCommand):
    help = (
        "Request ENDPOINT as a user and report every SQL query: totals, repeated queries "
        "grouped by cause (field, relation, why the optimiser did not fetch it) and the fix."
    )
    # A diagnosis must run even while a system check fails; `karni check` owns checks.
    requires_system_checks: list[Any] = []

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "endpoint",
            help="A path (/api/events/?page=2), a resource (events, events/<id>) or a viewset "
            "(EventViewSet, EventViewSet.retrieve).",
        )
        parser.add_argument(
            "--as",
            dest="user",
            default=None,
            help="The user: email, username or primary key (default: anonymous).",
        )
        parser.add_argument("--method", default="GET", help="HTTP method (default GET).")
        parser.add_argument(
            "--data", default=None, help="JSON request body (writes are rolled back)."
        )
        parser.add_argument("--json", action="store_true", help="Print the report as JSON.")
        parser.add_argument(
            "--explain", action="store_true", help="Add EXPLAIN plans for the slowest queries."
        )
        parser.add_argument("--all", action="store_true", help="List every statement.")

    def handle(self, *args: Any, **options: Any) -> None:
        from karni.api.diagnose import RequestFailed, run

        try:
            report = run(
                options["endpoint"],
                user=options["user"],
                method=options["method"],
                data=options["data"],
                explain=options["explain"],
            )
        except RequestFailed as failure:
            raise KarniCommandError(_failure_message(failure.text), code="E943") from None
        except KarniError as error:
            raise KarniCommandError(error.message, code=error.code) from None
        if options["json"]:
            self.stdout.write(
                json.dumps(report.as_dict(every=options["all"]), indent=2, ensure_ascii=False)
            )
        else:
            self.stdout.write(report.render(every=options["all"]))


def _failure_message(text: str) -> str:
    """The traceback, then what ``karni explain -`` says about it."""
    from django.conf import settings

    from karni.agent.rules import RULES
    from karni.errorcodes.failures import diagnose

    diagnosis = diagnose(
        text,
        root=getattr(settings, "BASE_DIR", None),
        rules=[rule.to_dict() for rule in RULES],
    )
    return (
        "The view raised while karni queries requested it, so there is no query report:\n\n"
        f"{text.rstrip()}\n\n{diagnosis.render()}"
    )
