"""``manage.py karni_context`` — compact machine-readable project inventory.

Deterministic, sorted, sections omitted when empty; consumed by AI agents via
the ``karni context`` CLI, so stdout carries data only (warnings go to stderr).
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from karni.introspect import build_context


class Command(BaseCommand):
    help = "Print the compact machine-readable project inventory."
    # Inventory must print even when system checks fail; `karni check` owns checks.
    requires_system_checks: list[Any] = []

    def handle(self, *args: Any, **options: Any) -> None:
        self.stdout.write(build_context())
