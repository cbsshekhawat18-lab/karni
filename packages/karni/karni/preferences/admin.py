"""Preferences in the admin: the details, section values and switches.

The details are one row: the list opens it, and it cannot be added twice or
deleted. Section values are checked against their section's model before
they are saved. A value the deployment fixes (``KARNI_PREFERENCES_LOCKED``)
is read only. Every change shows in the History of each row (audited).

Override / escape hatch: ``admin.site.unregister(Details)`` and register your
own, or subclass these classes.
"""

from __future__ import annotations

from typing import Any

from django.contrib import admin
from django.http import HttpRequest

from karni.admin import KarniModelAdmin
from karni.preferences import services
from karni.preferences.models import Details, SectionValue, Switch

__all__ = ["DetailsAdmin", "SectionValueAdmin", "SwitchAdmin"]


@admin.register(Details)
class DetailsAdmin(KarniModelAdmin):  # type: ignore[misc]
    """The business's details: one row."""

    list_display = ("__str__", "email", "phone", "time_zone", "currency", "updated_at")
    fieldsets = (
        (None, {"fields": ("name", "legal_name", "address", "phone", "email", "logo")}),
        ("Emails", {"fields": ("sender_name", "sender_email", "reply_to")}),
        ("Region", {"fields": ("time_zone", "language", "currency", "currency_display")}),
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        return super().has_add_permission(request) and not Details.objects.exists()

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def get_readonly_fields(self, request: HttpRequest, obj: Any = None) -> Any:
        return (*super().get_readonly_fields(request, obj), *services.locked_names("details"))

    def save_model(self, request: HttpRequest, obj: Any, form: Any, change: bool) -> None:
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(SectionValue)
class SectionValueAdmin(KarniModelAdmin):  # type: ignore[misc]
    """The values someone changed, per section. A field left out reads as its default."""

    list_display = ("section", "version", "updated_at", "updated_by")
    search_fields = ("section",)
    readonly_fields = ("version", "updated_at", "updated_by")

    def save_model(self, request: HttpRequest, obj: Any, form: Any, change: bool) -> None:
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(Switch)
class SwitchAdmin(KarniModelAdmin):  # type: ignore[misc]
    """Connections and email kinds someone switched. Without a row the default holds."""

    list_display = ("name", "kind", "on", "updated_at", "updated_by")
    list_filter = ("kind", "on")
    search_fields = ("name",)
    readonly_fields = ("updated_at", "updated_by")

    def save_model(self, request: HttpRequest, obj: Any, form: Any, change: bool) -> None:
        group = "connections" if obj.kind == Switch.Kind.CONNECTION else "emails"
        if services.locked(group, obj.name):
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied(f"{obj.name} is fixed by the deployment.")
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)
