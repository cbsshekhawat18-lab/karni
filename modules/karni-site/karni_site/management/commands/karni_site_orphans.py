"""``manage.py karni_site_orphans``: the blocks no template shows any more, listed or removed.

A block whose ``{% editable %}`` or ``{% editable_image %}`` left the templates stays in
the database, and *Page content* in the admin marks it (*in a template*: no). This command
lists those orphans (:mod:`karni_site.orphans` says how they are found and what the scan
cannot see), and the blocks it could not judge (*not seen*: a key built at run time could
be one of them).

Without ``--delete`` it only lists: nothing changes, so it is safe to run anywhere. With
``--delete`` it deletes the orphans nobody edited. An orphan someone edited is kept, and
named, unless ``--include-edited`` is given too: their text would be gone from the page if
the key came back to a template. A *not seen* block is never deleted. A delete is a soft
delete, as in the admin: the row and its history stay in the database.

Override / escape hatch: ``KARNI_SITE_CODE_BLOCKS`` names the keys code of your own stores,
which are never orphans.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from karni_site.orphans import TemplateKeys, classify, scan


class Command(BaseCommand):
    help = (
        "List the editable blocks no template shows any more (a dry run: nothing changes). "
        "--delete removes those nobody edited, --include-edited the edited ones too."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--delete",
            action="store_true",
            help="Delete the orphans nobody edited. Without it, nothing changes.",
        )
        parser.add_argument(
            "--include-edited",
            action="store_true",
            help="With --delete: delete the orphans someone edited too (their text is lost).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        from django.apps import apps

        if not apps.is_installed("karni_site"):
            self.stdout.write(
                "karni_site_orphans: karni_site is not in INSTALLED_APPS: nothing to do."
            )
            return
        from karni_site.models import Block

        found = scan()
        blocks = list(Block.objects.order_by("page", "position", "key"))
        statuses = classify((block.key for block in blocks), found)
        orphans = [block for block in blocks if statuses[block.key] is False]
        unseen = [block.key for block in blocks if statuses[block.key] is None]
        if not orphans:
            self.stdout.write(
                f"karni_site_orphans: no orphans. Of the {len(blocks)} block(s), "
                f"{len(blocks) - len(unseen)} are in a template."
            )
            self._unseen(unseen, found)
            return
        width = max(len(block.key) for block in orphans)
        self.stdout.write(
            f"karni_site_orphans: {len(orphans)} block(s) are in no template, so no page shows "
            "them:"
        )
        for block in orphans:
            state = "edited" if block.edited else "follows the template"
            self.stdout.write(f"  {block.key.ljust(width)}  {block.kind}, {state}")
        self._unseen(unseen, found)
        edited = [block for block in orphans if block.edited]
        untouched = [block for block in orphans if not block.edited]
        if not options["delete"]:
            advice = f" --delete removes the {len(untouched)} nobody edited." if untouched else ""
            if edited:
                advice += (
                    f" The {len(edited)} someone edited need --include-edited too, and their "
                    "text is lost."
                )
            alone = (
                " (--include-edited acts only with --delete)" if options["include_edited"] else ""
            )
            self.stdout.write(f"Nothing deleted: a dry run{alone}.{advice}")
            return
        doomed = orphans if options["include_edited"] else untouched
        for block in doomed:
            block.delete()  # a soft delete, as the admin's: it clears the page's cache
        self.stdout.write(
            f"Deleted {len(doomed)} block(s)"
            + (f": {', '.join(block.key for block in doomed)}." if doomed else ".")
        )
        kept = [block for block in edited if block not in doomed]
        if kept:
            self.stdout.write(
                f"Kept {len(kept)} that someone edited: "
                f"{', '.join(block.key for block in kept)}. --include-edited deletes them too."
            )

    def _unseen(self, keys: list[str], found: TemplateKeys) -> None:
        if not keys:
            return
        shown = ", ".join(keys[:10]) + (" ..." if len(keys) > 10 else "")
        if not found.tags:
            why = "no template has a block tag at all, so none can be judged"
        else:
            where = ", ".join(unread.where for unread in found.unread[:3])
            why = f"a key a template builds when its page renders could be one of them ({where})"
        self.stdout.write(
            f"Not seen: {len(keys)} block(s) no template names, kept because {why}: {shown}."
        )
