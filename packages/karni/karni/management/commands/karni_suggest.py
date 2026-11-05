"""``manage.py karni_suggest`` (experimental): the suggestions of :mod:`karni.suggestions`.

Prints the compact block, or with ``--json`` ``{version, enabled, suggestions}``
(the shape of ``docs/assets/karni-suggestions.schema.json``, which ``karni
suggest --json`` completes with the suggestions that read ``karni.yaml``). It
exits 0 whatever it finds: a suggestion never fails a run. ``karni doctor``
and ``karni suggest`` run it in the project's interpreter.
"""

from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from karni import suggestions


class Command(BaseCommand):
    help = "Print what Karni could do that the project does by hand (suggestions, experimental)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--json",
            action="store_true",
            help="Print {version, enabled, suggestions} as JSON (docs/assets/"
            "karni-suggestions.schema.json).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        found = [item.as_dict() for item in suggestions.detect()]
        if options["json"]:
            data = {
                "version": suggestions.VERSION,
                "enabled": suggestions.enabled(),
                "suggestions": found,
            }
            self.stdout.write(json.dumps(data, indent=2))
        elif found:
            self.stdout.write(suggestions.render(found))
        elif suggestions.enabled():
            self.stdout.write("suggestions: none")
        else:
            self.stdout.write("suggestions: off (KARNI_SUGGESTIONS = False)")
