"""``manage.py karni_site_seed``: render every page once, so its defaults are stored before a visit.

A template gives its defaults (``{% editable %}`` and ``{% editable_image %}``
blocks, a menu's ``seed``, ``{% site_defaults %}``), and the first render stores
them. Without this command that first render is a visitor's request, which then
writes to the database. Run it in a deploy, after ``migrate``: it requests every
page the way ``karni check --seo`` finds them (``/``, sitemap.xml, the named URLs
without arguments and every page they link to, up to ``KARNI_SITE_SEO_MAX_PAGES``)
through Django's test client, in this process, against the project's database.
It stores whatever a template gives that the database does not hold yet, and
follows what changed: a block or a menu item nobody edited takes the template's
new default. It seeds whatever ``KARNI_SITE_SEED_ON_RENDER`` says, so a site that
sets that to ``False`` writes nothing on a visitor's request and still gets its
defaults here. Storing defaults leaves no change-history entry
(:func:`karni.audit.capture.unrecorded`): it is nobody's edit.

It prints what it stored, and fails with ``SITE024`` when a page answers a
server error, naming the pages (``--keep-going`` reports them and exits 0).

Override / escape hatch: ``KARNI_SITE_SEO_IGNORE`` (paths never requested),
``KARNI_SITE_SEO_MAX_PAGES``, and :class:`karni_site.checks_seo.SeoCrawl`, whose
``crawl()`` this calls, for a crawl of your own.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser
from django.test.utils import override_settings
from karni.exceptions import KarniCommandError

CODE = "SITE024"


def _counts() -> dict[str, int]:
    from karni_site.models import Block, Menu, MenuItem
    from karni_site.sitesettings import settings_model

    return {
        "blocks": Block.objects.count(),
        "menus": Menu.objects.count(),
        "menu items": MenuItem.objects.count(),
        "site settings": settings_model()._default_manager.count(),
    }


class Command(BaseCommand):
    help = (
        "Render every page of the site once, so the blocks, menus and site details its "
        "templates give are stored before the first visitor. Run it in a deploy, after migrate."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--keep-going",
            action="store_true",
            help=f"Report pages that answer a server error without failing ({CODE}).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        from django.apps import apps
        from django.test import Client

        from karni_site.checks_seo import SeoCrawl, quiet_requests

        if not apps.is_installed("karni_site"):
            self.stdout.write(
                "karni_site_seed: karni_site is not in INSTALLED_APPS: nothing to do."
            )
            return
        before = _counts()
        hosts = [*getattr(settings, "ALLOWED_HOSTS", []), "testserver"]
        crawl = SeoCrawl(Client(raise_request_exception=False))
        with override_settings(
            ALLOWED_HOSTS=hosts, KARNI_SITE_SEED_ON_RENDER=True, KARNI_DEBUG_CAPTURE=False
        ):
            with quiet_requests() as errors:
                crawl.crawl()
        after = _counts()
        pages = [page for page in crawl.pages.values() if page.html]
        stored = ", ".join(
            f"{after[name] - before[name]} {name}" for name in after if after[name] > before[name]
        )
        self.stdout.write(
            f"karni_site_seed: rendered {len(pages)} page(s), {len(crawl.pages)} requested. "
            f"New: {stored or 'nothing'}."
        )
        failed = sorted(path for path, page in crawl.pages.items() if page.status >= 500)
        if not failed:
            return
        first = f" The first error logged: {errors[0]}" if errors else ""
        message = (
            f"{CODE}: {len(failed)} page(s) answer a server error, and their defaults are not "
            f"stored: {', '.join(failed[:10])}{' ...' if len(failed) > 10 else ''}.{first} Open "
            "one with `karni serve` to see the whole error."
        )
        if options.get("keep_going"):
            self.stderr.write(message)
            return
        raise KarniCommandError(message, code=CODE)
