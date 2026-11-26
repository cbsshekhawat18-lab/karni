"""Notifications in the admin: edited emails, the inboxes, switches, unsubscribes.

An edited email is checked by the restricted engine before it is saved, as the
Settings page checks it. Notifications are written by parts, never by hand: the
list is read only, and deleting a wrong one is allowed. Switches and
unsubscribes can be changed for a person who asks by phone.

Override / escape hatch: ``admin.site.unregister(Notification)`` and register
your own, or subclass these classes.
"""

from __future__ import annotations

from typing import Any

from django import forms
from django.contrib import admin
from django.http import HttpRequest

from karni.admin import KarniModelAdmin
from karni.mail import check_edited
from karni.notify.models import Choice, EmailTemplate, Notification, Unsubscribe

__all__ = ["ChoiceAdmin", "EmailTemplateAdmin", "NotificationAdmin", "UnsubscribeAdmin"]


class EmailTemplateForm(forms.ModelForm):  # type: ignore[type-arg]
    """An edited email, refused when the restricted engine refuses it."""

    class Meta:
        model = EmailTemplate
        fields = ("kind", "subject", "text")

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        problems = check_edited(str(cleaned.get("subject") or ""), str(cleaned.get("text") or ""))
        for part, problem in problems.items():
            self.add_error("text" if part == "text" else "subject", problem)
        return cleaned


@admin.register(EmailTemplate)
class EmailTemplateAdmin(KarniModelAdmin):  # type: ignore[misc]
    """The emails a business rewrote. Deleting one puts the files back."""

    form = EmailTemplateForm
    list_display = ("kind", "subject", "updated_at")
    search_fields = ("kind", "subject")


@admin.register(Notification)
class NotificationAdmin(KarniModelAdmin):  # type: ignore[misc]
    """Every inbox, newest first: filter by kind and by read, search the title."""

    list_display = ("title", "kind", "recipient", "created_at", "read_at")
    list_filter = ("kind", ("read_at", admin.EmptyFieldListFilter))
    search_fields = ("title", "kind", "recipient__email")
    readonly_fields = (
        "recipient",
        "kind",
        "title",
        "body",
        "link",
        "data",
        "read_at",
        "created_at",
    )
    list_select_related = ("recipient",)
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    def has_add_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


@admin.register(Choice)
class ChoiceAdmin(KarniModelAdmin):  # type: ignore[misc]
    """Each person's own switches: a kind they turned off, by channel."""

    list_display = ("user", "kind", "email", "inbox", "updated_at")
    list_filter = ("kind", "email", "inbox")
    search_fields = ("user__email", "kind")
    list_select_related = ("user",)
    raw_id_fields = ("user",)


@admin.register(Unsubscribe)
class UnsubscribeAdmin(KarniModelAdmin):  # type: ignore[misc]
    """The addresses that left a marketing kind, from the link in its email."""

    list_display = ("address", "kind", "created_at")
    list_filter = ("kind",)
    search_fields = ("address", "kind")
