"""``manage.py karni_rows '<requests>'`` (experimental): row counts for ``karni plan``.

Prints :func:`karni.facts.count_rows` for a JSON list of requests, each
``{"model": "app.Model", "field": ..., "kind": ..., "arg": ...}``, as
``{"rows": [...], "unreachable": {alias: why}}``. Only ``SELECT COUNT``
queries run: nothing is written. A database that does not answer is
reported, not raised, so ``karni plan`` can say why it shows no counts, and
requests that are not a JSON list of objects print ``{"rows": [], "error":
...}``.

Override / escape hatch: :func:`karni.facts.count_rows` is the importable form.
"""

from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from karni.facts import count_rows


class Command(BaseCommand):
    help = "Experimental. Count rows for karni plan: a JSON list of requests in, counts out."
    # The counts must print even when system checks fail: `karni check` owns checks.
    requires_system_checks: list[Any] = []

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("requests", help='A JSON list, e.g. [{"model": "shop.Order"}].')

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            requests = json.loads(options["requests"])
        except json.JSONDecodeError as exc:
            requests = f"not JSON: {exc}"
        if not isinstance(requests, list) or not all(isinstance(r, dict) for r in requests):
            why = requests if isinstance(requests, str) else "not a JSON list of objects"
            found: dict[str, Any] = {"rows": [], "error": f"The requests are {why}."}
        else:
            found = count_rows(requests)
        self.stdout.write(json.dumps(found, sort_keys=True))
