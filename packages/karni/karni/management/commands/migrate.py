"""Experimental. ``manage.py migrate``: Django's, with the autodetector ``makemigrations`` uses.

Django's check ``commands.E001`` asks the two commands to share one
autodetector, since ``migrate`` uses it to say that models have changes that
no migration holds. See :mod:`karni.management.commands.makemigrations`.
"""

from __future__ import annotations

from django.core.management.commands import migrate as django_migrate

from karni.migration_autodetector import KarniAutodetector


class Command(django_migrate.Command):
    autodetector = KarniAutodetector
