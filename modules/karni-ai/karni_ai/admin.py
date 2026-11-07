"""The usage log in the admin, read-only: every provider call, its tokens and its cost.

Override / escape hatch: ``admin.site.unregister(AICall)`` and register your
own ``KarniModelAdmin`` subclass.
"""

from __future__ import annotations

from typing import ClassVar

from django.contrib import admin
from karni.admin import KarniModelAdmin

from karni_ai.models import AICall

__all__ = ["AICallAdmin"]


@admin.register(AICall)
class AICallAdmin(KarniModelAdmin):
    """Experimental. Calls are logged, never added, changed or deleted by hand."""

    list_display: ClassVar[list[str]] = [
        "created_at",
        "user",
        "resource",
        "provider",
        "model",
        "input_tokens",
        "output_tokens",
        "cost",
        "status",
    ]
    list_filter: ClassVar[list[str]] = ["status", "provider", "model", "resource", "source"]
    search_fields: ClassVar[list[str]] = ["resource", "model", "user__email"]
    date_hierarchy = "created_at"

    def is_read_only(self) -> bool:
        return True
