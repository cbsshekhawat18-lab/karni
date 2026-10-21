"""The change log in the admin: read-only, searchable, and the History tab of audited models."""

from __future__ import annotations

from typing import Any

from django.contrib import admin
from django.http import HttpRequest

from karni.admin import KarniModelAdmin
from karni.audit.models import ChangeLog


@admin.register(ChangeLog)
class ChangeLogAdmin(KarniModelAdmin):
    """Every captured change, newest first. Nothing here is editable."""

    list_display = ("timestamp", "action", "content_type", "object_id", "actor")
    list_filter = ("action", "content_type")
    search_fields = ("object_id", "request_id")
    readonly_fields = (
        "timestamp",
        "action",
        "content_type",
        "object_id",
        "actor",
        "diff",
        "request_id",
    )
    date_hierarchy = "timestamp"
    ordering = ("-timestamp",)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False
