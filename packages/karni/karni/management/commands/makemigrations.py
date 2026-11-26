"""Experimental. ``manage.py makemigrations``: Django's, with Karni's autodetector.

The one difference is :class:`karni.migration_autodetector.KarniAutodetector`:
a generated field whose definition changed (``SearchField(sources=[...])``
with another source) is written as ``RemoveField`` and ``AddField``, since
``migrate`` cannot alter one in place. Every option is Django's.

Override / escape hatch: subclass this command and set ``autodetector``, or
put a ``makemigrations`` command of your own in an app listed before
``karni``.
"""

from __future__ import annotations

from django.core.management.commands import makemigrations as django_makemigrations

from karni.migration_autodetector import KarniAutodetector


class Command(django_makemigrations.Command):
    help = (
        "makemigrations, writing RemoveField + AddField for a generated field "
        "whose definition changed (Django cannot alter one in place)."
    )
    autodetector = KarniAutodetector
