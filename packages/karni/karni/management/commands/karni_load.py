"""``manage.py karni_load``: real content from a JSON or YAML file (``karni load``).

Rows are matched by natural key and created or updated, relations are named
by natural key, file fields hold paths relative to the content file, nested
lists hold children, and the whole file loads in one transaction with the
validation the API runs. ``--dry-run`` reports without writing,
``--refresh-files`` uploads every file again, ``--prune`` deletes children
the file does not list, ``--as USER`` records the actor, ``--json`` prints
the report as JSON. See :mod:`karni.transfer.loading`.

Override / escape hatch: :func:`karni.transfer.loading.load_content` is the
importable form and takes the importer class.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from karni.exceptions import KarniCommandError
from karni.transfer.loading import LoadError, find_user, load_content


class Command(BaseCommand):
    help = "Load real content from a JSON or YAML file: rows created or updated by natural key."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("file", help="The content file (.json, .yaml or .yml).")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Run everything, print what would change, and roll back.",
        )
        parser.add_argument(
            "--refresh-files",
            action="store_true",
            help="Upload every file again, not only the ones rows lack.",
        )
        parser.add_argument(
            "--prune",
            action="store_true",
            help="Delete children of a listed row that its list does not name.",
        )
        parser.add_argument(
            "--as",
            dest="as_user",
            metavar="USER",
            help="Record this user (email, username or pk) as the actor of every write.",
        )
        parser.add_argument("--json", action="store_true", help="Print the report as JSON.")

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            actor = find_user(options["as_user"]) if options["as_user"] else None
            report = load_content(
                Path(options["file"]),
                actor=actor,
                dry_run=options["dry_run"],
                refresh_files=options["refresh_files"],
                prune=options["prune"],
            )
        except LoadError as exc:
            raise KarniCommandError(exc.message, code=exc.code) from exc
        if options["json"]:
            self.stdout.write(json.dumps(report.to_dict(), indent=2))
        else:
            self.stdout.write(report.render())
