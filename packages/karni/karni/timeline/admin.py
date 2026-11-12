"""Experimental. The timeline in the admin: entries, newest first, with the records they show on.

Entries are written by parts and by family events, never by hand here: the
list is read only. Deleting an entry is allowed, for a wrong one.

Override / escape hatch: ``admin.site.unregister(TimelineEntry)`` and
register your own, or subclass :class:`TimelineEntryAdmin`.
"""

from __future__ import annotations

from typing import Any

from django.contrib import admin
from django.http import HttpRequest
from unfold.admin import TabularInline

from karni.admin import KarniModelAdmin
from karni.timeline.models import TimelineEntry, TimelineLink

__all__ = ["TimelineEntryAdmin", "TimelineLinkInline"]


class TimelineLinkInline(TabularInline):  # type: ignore[misc]
    """The records an entry shows on."""

    model = TimelineLink
    extra = 0
    fields = ("content_type", "object_id")
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


@admin.register(TimelineEntry)
class TimelineEntryAdmin(KarniModelAdmin):  # type: ignore[misc]
    """Every entry, newest first: filter by kind and part, search the title."""

    list_display = ("title", "kind", "occurred_at", "person", "source", "actor")
    list_filter = ("source", "kind")
    search_fields = ("title", "kind", "=event_id", "person__display_name", "person__email")
    readonly_fields = (
        "id",
        "occurred_at",
        "kind",
        "title",
        "body",
        "source",
        "actor",
        "person",
        "event_id",
        "data",
        "created_at",
    )
    list_select_related = ("person", "actor")
    date_hierarchy = "occurred_at"
    ordering = ("-occurred_at",)
    inlines = [TimelineLinkInline]

    def has_add_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False
