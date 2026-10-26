"""``manage.py karni_publish_web``: the web server's files, from this release, into a directory.

The release step of ``docker-compose.prod.yml`` runs it after ``migrate`` and
``collectstatic``. It writes the Caddyfile, the security-headers snippet and
the built staff app into ``--root`` (``/data/web``, on the volume Caddy reads),
as :mod:`karni.deploy.web` describes.

Override / escape hatch: ``--root``, ``--app`` (``""`` skips the staff app),
``--caddyfile`` (``""`` skips it) and ``--keep-days``. Relative paths are read
from the directory the command runs in (the project, ``/app`` in the image).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from karni.deploy.web import describe, publish


class Command(BaseCommand):
    help = "Publish the Caddyfile, the security headers and the built staff app for Caddy."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--root", default="/data/web", help="where to write (/data/web)")
        parser.add_argument(
            "--app", default="frontend/dist", help="the built staff app (frontend/dist)"
        )
        parser.add_argument("--caddyfile", default="Caddyfile", help="the Caddyfile (Caddyfile)")
        parser.add_argument(
            "--keep-days",
            type=float,
            default=7.0,
            help="days an earlier build's files stay for open browsers (7)",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        result = publish(
            Path(options["root"]),
            app=Path(options["app"]) if options["app"] else None,
            caddyfile=Path(options["caddyfile"]) if options["caddyfile"] else None,
            keep_days=float(options["keep_days"]),
        )
        self.stdout.write("published:\n" + describe(result.written))
        if result.skipped:
            self.stdout.write("skipped:\n" + describe(result.skipped))
