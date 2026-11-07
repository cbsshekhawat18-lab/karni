"""``manage.py karni_context`` — compact machine-readable project inventory.

Deterministic, sorted, sections omitted when empty; consumed by AI agents via
the ``karni context`` CLI, so stdout carries data only (warnings go to stderr).

Slices (experimental), for a project too large to read at once: ``--summary``
prints one line per app, ``--app LABEL`` one app in full and ``--model NAME``
(repeatable) one model in depth (:mod:`karni.introspect`). ``--app`` and
``--model`` combine: the app slices first, then each model. An unknown name
fails with ``E470`` (``E471`` for a bare name two apps share).
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from karni.exceptions import KarniCommandError
from karni.introspect import (
    ContextSliceError,
    app_context,
    build_context,
    model_context,
    summary_context,
)


class Command(BaseCommand):
    help = "Print the compact machine-readable project inventory."
    # Inventory must print even when system checks fail; `karni check` owns checks.
    requires_system_checks: list[Any] = []

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--app",
            action="append",
            default=[],
            metavar="LABEL",
            help="Only this app, in full (repeatable). Experimental.",
        )
        parser.add_argument(
            "--model",
            action="append",
            default=[],
            metavar="NAME",
            help="One model in depth: Name or app_label.Name (repeatable). Experimental.",
        )
        parser.add_argument(
            "--summary",
            action="store_true",
            help="One line per app: its models and viewsets. Experimental.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        apps_, names, summary = options["app"], options["model"], options["summary"]
        try:
            if summary:
                text = summary_context()
            elif apps_ or names:
                parts = [app_context(apps_)] if apps_ else []
                if names:
                    parts.append(model_context(names))
                text = "\n".join(parts)
            else:
                text = build_context()
        except ContextSliceError as exc:
            raise KarniCommandError(exc.message, code=exc.code) from None
        self.stdout.write(text)
