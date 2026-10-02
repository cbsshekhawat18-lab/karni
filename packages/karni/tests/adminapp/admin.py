"""Explicit registration that karni's autodiscovery must leave untouched.

Imported by ``django.contrib.admin``'s own autodiscovery (during *its*
``ready()``), which runs before ``karni.admin``'s — exactly how a project
``admin.py`` behaves.
"""

from __future__ import annotations

from django.contrib import admin

from tests.adminapp.models import Explicit


@admin.register(Explicit)
class ExplicitAdmin(admin.ModelAdmin):
    """Stock hand-written admin: explicit registration always wins."""

    list_display = ("id", "name")
