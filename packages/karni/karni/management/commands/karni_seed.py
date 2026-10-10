"""``manage.py karni_seed`` — realistic, deterministic demo data (``karni seed``).

Seeds every model of the project's apps (plus the user model and any model
a ``<app>/seeds.py`` seeder names), relation targets first, with values
inferred from field names and types, and prints what it created and the demo
login. ``--count`` rows per model, ``--seed`` for reproducible data,
``--reset`` to wipe the project's tables first, ``--model`` (repeatable) to
narrow the run, ``--json`` for machine output. It refuses to run with
``DEBUG = False`` (a production database) unless ``--force`` is given.

Override / escape hatch: :func:`karni.seeding.seed` is the importable form;
per-model overrides live in ``<app>/seeds.py`` (see :mod:`karni.seeding`).
"""

from __future__ import annotations

import json
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser

from karni.exceptions import KarniCommandError
from karni.seeding import DEFAULT_COUNT, DEFAULT_SEED, SeedError, seed


class Command(BaseCommand):
    help = "Seed realistic, deterministic demo data inferred from the models."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--count", type=int, default=DEFAULT_COUNT, help="Rows per model (default 10)."
        )
        parser.add_argument(
            "--seed", default=str(DEFAULT_SEED), help="Random seed; the same seed, the same rows."
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete the project models' rows first (users are kept).",
        )
        parser.add_argument(
            "--model",
            action="append",
            default=[],
            metavar="APP.MODEL",
            help="Only seed this model (repeatable).",
        )
        parser.add_argument("--force", action="store_true", help="Seed even though DEBUG is False.")
        parser.add_argument("--json", action="store_true", help="Print the report as JSON.")

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG and not options["force"]:
            raise KarniCommandError(
                "Refusing to seed: DEBUG is False, so this may be a production database, and "
                "seeding creates a demo superuser with a known password. Pass --force if you "
                "really mean it.",
                code="E615",
            )
        if options["count"] < 0:
            raise KarniCommandError("--count must be 0 or more.", code="E614")
        raw_seed = options["seed"]
        seed_value: int | str = int(raw_seed) if str(raw_seed).lstrip("-").isdigit() else raw_seed
        try:
            report = seed(
                count=options["count"],
                seed=seed_value,
                reset=options["reset"],
                models=options["model"] or None,
            )
        except SeedError as exc:
            raise KarniCommandError(exc.message, code=exc.code) from exc
        if options["json"]:
            self.stdout.write(json.dumps(report.to_dict(), indent=2))
        else:
            self.stdout.write(report.render())
