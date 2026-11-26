"""Explicit registration that karni's autodiscovery must leave untouched.

Imported by ``django.contrib.admin``'s own autodiscovery (during *its*
``ready()``), which runs before ``karni.admin``'s — exactly how a project
``admin.py`` behaves.
"""

from __future__ import annotations

from django.contrib import admin

from karni.admin import KarniModelAdmin
from tests.adminapp.models import Explicit, Handmade


# karni: allow(admin-convention): a stock admin, to prove explicit registration wins
@admin.register(Explicit)
class ExplicitAdmin(admin.ModelAdmin):
    """Stock hand-written admin: explicit registration always wins."""

    list_display = ("id", "name")


@admin.register(Handmade)
class HandmadeAdmin(KarniModelAdmin):
    """A hand-registered Karni admin that sets none of the model's AdminMeta options.

    ``Handmade.AdminMeta`` (columns, search, rows per page) and the inline that
    ``HandmadePart.AdminMeta.inline_on`` declares still apply to it.
    """

    save_on_top = True
