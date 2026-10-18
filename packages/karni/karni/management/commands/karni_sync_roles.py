"""``manage.py karni_sync_roles`` — the role tables from ``KARNI_ROLES`` (``karni sync-roles``).

Creates and updates the :class:`~karni.accounts.models.Role`,
:class:`~karni.accounts.models.Permission` and
:class:`~karni.accounts.models.RolePermission` rows the declaration describes,
reports the roles the database holds that the declaration no longer names, and
deletes nothing. The same sync runs after every ``migrate`` unless
``KARNI_ROLES_AUTOSYNC`` is ``False``.

Override / escape hatch: :func:`karni.accounts.roles.sync_roles` is the
importable form and takes a declaration of its own.
"""

from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from karni.accounts.roles import sync_roles


class Command(BaseCommand):
    help = "Create or update the roles and grants KARNI_ROLES declares; never deletes."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--dry-run", action="store_true", help="Report what would change; write nothing."
        )
        parser.add_argument("--json", action="store_true", help="Print the report as JSON.")

    def handle(self, *args: Any, **options: Any) -> None:
        report = sync_roles(dry_run=options["dry_run"])
        if options["json"]:
            self.stdout.write(json.dumps(report.to_dict(), indent=2))
        else:
            self.stdout.write(report.render())
