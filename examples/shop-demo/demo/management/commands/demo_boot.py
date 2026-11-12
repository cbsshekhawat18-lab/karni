"""``manage.py demo_boot``: migrate, then seed an empty database or reset old data.

The start command (``scripts/start.sh``) runs it once, before the web server
starts, so no worker serves a request while it runs. It refuses while
``DEMO_MODE`` is off and ``DEBUG`` is off: the seed makes a superuser with a
known password, which only a public demo wants.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from demo import account, reset


class Command(BaseCommand):
    help = "Migrate, then seed an empty database or reset demo data older than DEMO_RESET_HOURS."

    def handle(self, *args: Any, **options: Any) -> None:
        if not account.demo_mode() and not settings.DEBUG:
            raise CommandError(
                "Refusing to boot the demo: DEMO_MODE is off and DEBUG is off. The seed makes a "
                "superuser with a known password. Set DEMO_MODE=True for the public demo."
            )
        call_command("migrate", interactive=False, verbosity=max(int(options["verbosity"]) - 1, 0))
        self.stdout.write(reset.boot())
