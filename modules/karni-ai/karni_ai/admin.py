"""The usage log in the admin, read-only: every provider call, its job, its counts and its cost.

Each count is shown with its unit (``812 tokens``, ``1240 characters``): a job of the
project's own may be billed in another unit than tokens.

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
    """Calls are logged, never added, changed or deleted by hand."""

    list_display: ClassVar[list[str]] = [
        "created_at",
        "user",
        "kind",
        "resource",
        "provider",
        "model",
        "input_count",
        "output_count",
        "cost",
        "status",
    ]
    list_filter: ClassVar[list[str]] = [
        "status",
        "kind",
        "provider",
        "model",
        "resource",
        "source",
        "unit",
    ]
    search_fields: ClassVar[list[str]] = ["resource", "model", "user__email"]
    date_hierarchy = "created_at"

    def is_read_only(self) -> bool:
        return True

    @admin.display(description="input", ordering="input_tokens")
    def input_count(self, obj: AICall) -> str:
        """The input count with its unit: ``812 tokens``, ``1240 characters``."""
        return f"{obj.input_tokens} {obj.unit}"

    @admin.display(description="output", ordering="output_tokens")
    def output_count(self, obj: AICall) -> str:
        return f"{obj.output_tokens} {obj.unit}"
