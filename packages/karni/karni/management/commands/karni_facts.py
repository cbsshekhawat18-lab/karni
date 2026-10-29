"""``manage.py karni_facts`` (experimental): the project as JSON facts, for ``karni spec export``.

Prints :func:`karni.facts.project_facts`: the project's models with each
field's class and ``deconstruct()`` arguments, the routed viewsets with
their access, the settings behind roles and features, the installed modules'
settings and the seeders. Nothing is written and the database is not opened.

Override / escape hatch: :func:`karni.facts.project_facts` is the importable
form, and ``KARNI_FACTS_APPS`` names the apps to describe.
"""

from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand

from karni.facts import project_facts


class Command(BaseCommand):
    help = "Experimental. Print the project's models, viewsets, roles and modules as JSON."
    # The facts must print even when system checks fail: `karni check` owns checks.
    requires_system_checks: list[Any] = []

    def handle(self, *args: Any, **options: Any) -> None:
        self.stdout.write(json.dumps(project_facts(), indent=1, sort_keys=True))
