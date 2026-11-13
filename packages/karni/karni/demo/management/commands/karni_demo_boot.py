"""``manage.py karni_demo_boot``: migrate, then seed an empty database or reset old data.

The start command runs it once, before the web server starts, so no worker serves
a request while it runs::

    python manage.py karni_demo_boot
    exec gunicorn config.asgi:application ...

It refuses (``E951``) while ``KARNI_DEMO_MODE`` is off and ``DEBUG`` is off: the
seed makes accounts with a known password, which only a public demo wants.
``--no-migrate`` skips the migration step.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandParser

from karni.demo import conf, reset
from karni.exceptions import KarniCommandError


class Command(BaseCommand):
    help = (
        "Migrate, then seed an empty database or reset demo data older than KARNI_DEMO_RESET_HOURS."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--no-migrate", action="store_true", help="Skip the migration step.")

    def handle(self, *args: Any, **options: Any) -> None:
        if not conf.demo_mode() and not settings.DEBUG:
            raise KarniCommandError(
                "Refusing to boot the demo: KARNI_DEMO_MODE is off and DEBUG is off. The seed "
                "makes accounts with a known password. Set KARNI_DEMO_MODE=True "
                "(or DEMO_MODE=True) for the public demo.",
                code="E951",
            )
        if not options["no_migrate"]:
            call_command(
                "migrate", interactive=False, verbosity=max(int(options["verbosity"]) - 1, 0)
            )
        self.stdout.write(reset.boot())
